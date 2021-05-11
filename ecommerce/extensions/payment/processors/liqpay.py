# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import hashlib
import json
import logging
from base64 import b64decode, b64encode
from decimal import Decimal

from datetime import datetime, timedelta

import requests
from django.urls import reverse
from oscar.apps.payment.exceptions import GatewayError
from urllib.parse import urljoin

from ecommerce.core.url_utils import get_ecommerce_url
from ecommerce.extensions.payment.exceptions import DuplicateReferenceNumber, InvalidSignatureError, LiqPayWaitSecureStatus
from ecommerce.extensions.payment.processors import BasePaymentProcessor, HandledProcessorResponse


logger = logging.getLogger(__name__)

class Liqpay(BasePaymentProcessor): 
    """Implementation of the LiqPay credit card processor using the Callback API 3.0"""

    NAME = "liqpay"


    def __init__(self, site):
        super(Liqpay, self).__init__(site)
        configuration = self.configuration

        self.keys = configuration['keys']
        self.version = configuration.get('version', 3) #3
        self.sandbox = configuration.get('sandbox', 0) #0
        self.currency = configuration['currency'] #UAH
        self.language = configuration['language'] #uk

        #self.public_key = configuration['keys']['lvbs']['public_key']
        #self.private_key = configuration['keys']['lvbs']['private_key']
        self.public_key = ''
        self.private_key = ''

    @property
    def cancel_url(self):
        return get_ecommerce_url(self.configuration['cancel_checkout_path'])

    @property
    def error_url(self):
        return get_ecommerce_url(self.configuration['error_path'])


    def _make_signature(self, *args):
        joined_fields = "".join(x for x in args).encode("utf-8")
        return b64encode(hashlib.sha1(joined_fields).digest()).decode("ascii")

    def make_signature(self, params):
        data_to_sign = b64encode(json.dumps(params).encode("utf-8")).decode("ascii")
        return self._make_signature(self.private_key, data_to_sign, self.private_key)


    def get_transaction_parameters(self, basket, request=None, use_client_side_checkout=False, **kwargs):
        """ Generate a dictionary of signed parameters required for this processor to complete a transaction.

        Arguments:
            use_client_side_checkout:
            basket (Basket): The basket of products being purchased.
            request (Request, optional): A Request object which can be used to construct an absolute URL in
                cases where one is required.
            use_client_side_checkout (bool, optional): Determines if client-side checkout should be used.
            **kwargs: Additional parameters.

        Returns:
            dict: Payment processor-specific parameters required to complete a transaction. At a minimum,
                this dict must include a `payment_page_url` indicating the location of the processor's
                hosted payment page.
        """

        self._set_keys_from_basket(basket)

        params = self._generate_parameters(basket)

        return {
            'payment_page_url':urljoin(self.configuration['host'], '3/checkout'),
            'signature': self.make_signature(params),
            'data': b64encode(json.dumps(params).encode("utf-8")).decode("ascii"),
        }

    def _set_keys_from_basket(self, basket):
        partner = 'prima'

        #org_ids = self._get_org_ids(basket)
        #if len(org_ids) == 1 and org_ids[0].lower() in self.keys:
        #    partner = org_ids[0].lower()

        self.public_key = self.keys[partner]['public_key']
        self.private_key = self.keys[partner]['private_key']

    def _get_org_ids(self, basket):
        """
        Get Organizaiton IDs from basket
        Arguments:
            basket: basket with items
        Returns:
             String containing organization id.
        """
        org_ids = []

        for line in basket.all_lines():
            line_course = line.product.course
            if line_course:
                courseid = line_course.id
                if 'course-v1:' in courseid:
                    org_ids.append(courseid.replace('course-v1:','').split('+')[0])
                else:
                    org_ids.append(courseid.split('/')[0])
        return org_ids

    def _generate_parameters(self, basket):
        """ Generates the parameters dict.

        A signature is NOT included in the parameters.

         Arguments:
            basket (Basket): Basket from which the pricing and item details are pulled.
            use_sop_profile (bool, optional): Indicates if the Silent Order POST profile should be used.
            **kwargs: Additional parameters to add to the generated dict.

         Returns:
             dict: Dictionary containing the payment parameters that should be sent to LiqPay.
        """

        sandbox = self.sandbox

        username = basket.owner.username
        if username in ['parhom','parhom_999','Ivan','Alena_Sorokina','voyt2365','presli277','banderos1902','agutin_zirochka','john.lennon','ilon.mask.zirochka','super_freddiemercury','salvador_dali_12']:
            sandbox = 1

        course_name = ''
        for line in basket.all_lines():
            course_name = line.product.title.replace("Seat in ","")
            course_name = course_name.replace(" with professional certificate","")
            break

        if sandbox:
            course_name += ' (sandbox)'
        expired = datetime.utcnow() + timedelta(hours=2)

        return {
            "public_key": self.public_key,
            "description": u"Оплата онлайн-курсу \"{}\", замовлення {}".format(course_name, basket.order_number),
            "order_id": basket.order_number,
            "currency": "UAH",
            "result_url": urljoin(get_ecommerce_url(), reverse('liqpay:processed')) + '?id=' + str(basket.id),
            "server_url": urljoin(get_ecommerce_url(), reverse('liqpay:callback')),
            "language": self.language,
            "amount": str(basket.total_incl_tax),
            "expired_date": expired.strftime("%Y-%m-%d %H:%M:%S"),
            "sandbox": sandbox,
            "version": self.version,
            "action": "pay",
        }


    def handle_processor_response(self, response, basket=None):
        """
        Handle a response from the payment processor.

        This method creates PaymentEvents and Sources for successful payments.

        Arguments:
            response (dict): Dictionary of parameters received from the payment processor

        Keyword Arguments:
            basket (Basket): Basket whose contents have been purchased via the payment processor

        Returns:
            HandledProcessorResponse
        """
        # NOTE(smandziuk): Validate the signature (indicating potential tampering)
        data = response.get('data')

        self._set_keys_from_basket(basket)

        sign_string = str(self.private_key) + str(data) + str(self.private_key)
        sign = b64encode(hashlib.sha1(sign_string.encode("utf-8")).digest()).decode("ascii")
        if sign != response.get('signature'):
            msg = 'Signatures do not match. Payment data has modified by a third party.'
            logger.exception(msg)
            raise InvalidSignatureError(msg)

        decode_data = json.loads(b64decode(data).decode('utf-8'))
        transaction_id = decode_data.get('payment_id')
        transaction_state = decode_data['status'].lower()

        # NOTE(smandziuk): Raise an exception for payments that were not accepted.
        if transaction_state not in ('success', 'sandbox'):
            error_code = decode_data.get('err_code')
            error_description = decode_data.get('err_decription')
            
            if transaction_state == 'wait_secure':
                self.record_processor_response(decode_data, transaction_id=transaction_id, basket=basket)
                raise LiqPayWaitSecureStatus('Order {id} got wait_secure status'.format(id=decode_data.get('order_id')))
            
            if transaction_state in ('error', 'failure') and error_code == 'order_id_duplicate':
                self.record_processor_response(decode_data, transaction_id=transaction_id, basket=basket)
                raise DuplicateReferenceNumber('Order_id [{id}] is duplicated.'.format(id=decode_data.get('order_id')))
            
            msg = 'Status: {status}, code: {error_code} - {err_description}'.format(
                status=transaction_state, error_code=error_code, err_description=error_description
            )
            logger.error(msg)
            self.record_processor_response(decode_data, transaction_id=transaction_id, basket=basket)
            raise GatewayError(msg)

        self.record_processor_response(decode_data, transaction_id=transaction_id, basket=basket)
        logger.info("Successfully executed LiqPay payment [%s] for basket [%d].", transaction_id, basket.id)

        currency = decode_data.get('currency')
        total = Decimal(decode_data.get('amount'))
        card_number = decode_data.get('sender_card_mask2')
        card_type = decode_data.get('sender_card_type')

        return HandledProcessorResponse(
            transaction_id=transaction_id,
            total=total,
            currency=currency,
            card_number=card_number,
            card_type=card_type
        )


    def issue_credit(self, order, reference_number, amount, currency):
        """
        Issue a credit for the specified transaction.

        Arguments:
            order (Order): Order being refunded.
            reference_number (str): Reference number of the transaction being refunded.
            amount (Decimal): amount to be credited/refunded
            currency (string): currency of the amount to be credited

        Returns:
            str: Reference number of the *refund* transaction. Unless the payment processor groups related transactions,
             this will *NOT* be the same as the `reference_number` argument.
        """
        order_number = order.number
        basket = order.basket
        
        params = {
            'action': 'refund',
            'public_key': self.public_key,
            'version': self.version,
            'order_id': order_number,
            'amount': str(amount),
            'payment_id': reference_number,
            'currency': currency,
        }
        refund_data = {
            'signature': self._make_signature(self.private_key, params, self.private_key),
            'data': b64encode(json.dumps(params).encode("utf-8")).decode("ascii"),
        }
        refund_url = urljoin(self.configuration['host'], 'request')
        refund_response = requests.post(refund_url, data=refund_data, verify=False)
        response = json.loads(refund_response.content.decode("utf-8"))
        transaction_state = response.get('status').lower()
        transaction_id = response.get('payment_id')
        ppr = self.record_processor_response(response, transaction_id=transaction_id, basket=basket)

        if transaction_state in ('success', 'reversed', 'sandbox'):
            return transaction_id
        else:
            msg = "Failed to refund LiqPay payment [{transaction_id}] with status [{status}]. " \
                  "LiqPay's response was recorded in entry [{response_id}].".format(
                      transaction_id=transaction_id, status=transaction_state, response_id=ppr.id
                  )
            logger.exception(msg)
            raise GatewayError(msg)
