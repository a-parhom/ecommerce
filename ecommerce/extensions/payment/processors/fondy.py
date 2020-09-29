# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import json
import logging
from base64 import b64decode, b64encode
from decimal import Decimal
from hashlib import sha1

import requests
from django.urls import reverse
from oscar.apps.payment.exceptions import GatewayError
from urlparse import urljoin

from ecommerce.core.url_utils import get_ecommerce_url
from ecommerce.extensions.payment.exceptions import DuplicateReferenceNumber, InvalidSignatureError
from ecommerce.extensions.payment.processors import BasePaymentProcessor, HandledProcessorResponse


logger = logging.getLogger(__name__)

class Fondy(BasePaymentProcessor): 
    """Implementation of the Fondy credit card processor"""

    NAME = "fondy"


    def __init__(self, site):
        super(Fondy, self).__init__(site)
        configuration = self.configuration

        self.version = configuration.get('version', '1.0.1') 
        self.currency = configuration['currency'] #UAH
        self.lang = configuration['lang'] #uk

        self.merchant_id = configuration['merchant_id']
        self.merchant_password = configuration['merchant_password']

    @property
    def cancel_url(self):
        return get_ecommerce_url(self.configuration['cancel_checkout_path'])

    @property
    def error_url(self):
        return get_ecommerce_url(self.configuration['error_path'])


    def make_signature(self, params):
        data = [self.merchant_password]
        data.extend([unicode(params[key]) for key in sorted(iter(params.keys()))
                     if params[key] != '' and not params[key] is None])
        return sha1("|".join(data).encode('utf-8')).hexdigest()


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

        params = self._generate_parameters(basket)
        params.update({
            'payment_page_url':urljoin(self.configuration['host'], 'checkout/redirect/'),
            'signature': self.make_signature(params),
        })
        logger.exception(str(params))
        return params

    def _generate_parameters(self, basket):
        """ Generates the parameters dict.

        A signature is NOT included in the parameters.

         Arguments:
            basket (Basket): Basket from which the pricing and item details are pulled.
            use_sop_profile (bool, optional): Indicates if the Silent Order POST profile should be used.
            **kwargs: Additional parameters to add to the generated dict.

         Returns:
             dict: Dictionary containing the payment parameters that should be sent to Fondy.
        """

        username = basket.owner.username
        if (username in ['parhom_999','Ivan','Alena_Sorokina']):
            self.merchant_id = '1396424'
            self.merchant_password = 'test'

        course_name = ''
        for line in basket.all_lines():
            course_name = line.product.title.replace("Seat in ","")
            course_name = course_name.replace(" with professional certificate","")
            break

        return {
            "merchant_id": self.merchant_id,
            "order_desc": u"Оплата онлайн-курсу \"{}\", замовлення {}".format(course_name, basket.order_number),
            "order_id": basket.order_number,
            "currency": self.currency,
            "response_url": urljoin(get_ecommerce_url(), reverse('fondy:result')),            
            "lang": self.lang,
            "merchant_data": str(basket.id),
            "amount": int(basket.total_incl_tax * 100),
            "version": self.version,
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

        data = response

        if 'signature' in data:
            result_signature = data['signature']
            del data['signature']
        else:
            msg = 'Incorrect data'
            logger.exception(msg)
            raise ValueError(msg)
        if 'response_signature_string' in data:
            del data['response_signature_string']
        signature = self.make_signature(data)

        if signature != result_signature:
            msg = 'Signatures do not match. Payment data has been modified by a third party.'
            logger.exception(msg)
            raise InvalidSignatureError(msg)

        transaction_id = data.get('payment_id')
        transaction_state = data['response_status'].lower()

        # NOTE(smandziuk): Raise an exception for payments that were not accepted.
        if transaction_state not in ('success', 'sandbox'):
            error_code = data.get('response_code')
            error_description = data.get('response_description')
            if transaction_state in ('error', 'failure') and error_code == '1013': #1013 - Duplicate order_id for merchant
                raise DuplicateReferenceNumber('Order_id [{id}] is duplicated.'.format(id=data.get('order_id')))
            msg = 'Status: {status}, code: {error_code} - {err_description}'.format(
                status=transaction_state, error_code=error_code, err_description=error_description
            )
            logger.error(msg)
            raise GatewayError(msg)

        self.record_processor_response(data, transaction_id=transaction_id, basket=basket)
        logger.info("Successfully executed Fondy payment [%s] for basket [%d].", transaction_id, basket.id)

        currency = data.get('currency')
        total = Decimal(data.get('amount')) / 100
        card_number = data.get('masked_card')
        card_type = data.get('card_type')

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
            'merchant_id': self.merchant_id,
            'version': self.version,
            'order_id': order_number,
            'amount': int(amount * 100),
            'currency': currency,
        }
        params.update({
            'signature': self.make_signature(params),
        })

        refund_data = params

        refund_url = urljoin(self.configuration['host'], 'reverse/order_id')

        headers = {
            'User-Agent': 'Python SDK',
            'Content-Type': 'application/json',
        }

        request = {'request': refund_data}

        refund_response = requests.post(refund_url, data=json.dumps(request), headers=headers)
        response = json.loads(refund_response.content.decode("utf-8"))

        transaction_state = response['response'].get('response_status').lower()
        transaction_id = reference_number

        ppr = self.record_processor_response(response['response'], transaction_id=transaction_id, basket=basket)

        if transaction_state in ('success', 'reversed', 'sandbox'):
            return transaction_id
        else:
            error_message = response['response']['error_message']
            msg = "Failed to refund Fondy payment [{transaction_id}] with status [{status}]. " \
                  "Fondy's response was recorded in entry [{response_id}].".format(
                      transaction_id=transaction_id, status=error_message, response_id=ppr.id
                  )
            logger.exception(msg)
            raise GatewayError(msg)
