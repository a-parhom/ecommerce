# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import hashlib
import json
import logging
from base64 import b64decode, b64encode
from decimal import Decimal
from hashlib import sha1

import requests
from django.urls import reverse
from oscar.apps.payment.exceptions import GatewayError
from urllib.parse import urljoin

from ecommerce.core.url_utils import get_ecommerce_url
from ecommerce.extensions.payment.exceptions import DuplicateReferenceNumber, InvalidSignatureError, AuthorizationError
from ecommerce.extensions.payment.processors import BasePaymentProcessor, HandledProcessorResponse


logger = logging.getLogger(__name__)

class Privatparts(BasePaymentProcessor): 
    """Implementation of the PrivatParts credit card processor"""

    NAME = "privatparts"

    def __init__(self, site):
        super(Privatparts, self).__init__(site)
        configuration = self.configuration

        self.store_id = configuration['store_id']
        self.password = configuration['password']
        self.parts_count = configuration['parts_count']
        self.currency = 'uah'
        self.sandbox = configuration['sandbox']

        if self.sandbox:
            self.store_id = '4AAD1369CF734B64B70F'
            self.password = '75bef16bfdce4d0e9c0ad5a19b9940df'

    @property
    def cancel_url(self):
        return get_ecommerce_url(self.configuration['cancel_checkout_path'])

    @property
    def error_url(self):
        return get_ecommerce_url(self.configuration['error_path'])

    def make_signature(self, *args):
        joined_fields = "".join(x for x in args).encode("utf-8")
        signature = b64encode(hashlib.sha1(self.password.encode("utf-8") + joined_fields +self.password.encode("utf-8")).digest()).decode("ascii")
        
        return signature

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

        sandbox = self.sandbox

        self._check_sandbox_required(basket)

        course_name = ''
        for line in basket.all_lines():
            course_name = line.product.title.replace("Seat in ","")
            course_name = course_name.replace(" with professional certificate","")
            break

        params = {
            "storeId": self.store_id,
            "orderId": basket.order_number,
            "amount": str(basket.total_incl_tax),
            "partsCount": self.parts_count,
            "merchantType": "II",
            "products": [
                {
                    "name": u"Оплата онлайн-курсу \"{}\", замовлення {}".format(course_name, basket.order_number),
                    "count": 1,
                    "price": str(basket.total_incl_tax)
                },
            ],
            "responseUrl": urljoin(get_ecommerce_url(), reverse('privatparts:callback')) + '?orderId=' + str(basket.order_number),
            "redirectUrl": urljoin(get_ecommerce_url(), reverse('privatparts:processed')) + '?id=' + str(basket.id),
        }

        signature = self.make_signature(
            params['storeId'],
            params['orderId'],
            str( int (float(params['amount']) * 100) ),
            str(params['partsCount']),
            params['merchantType'],
            params['responseUrl'],
            params['redirectUrl'],
            params['products'][0]['name'],
            str(params['products'][0]['count']),
            str( int (float(params['products'][0]['price']) * 100) )
        )

        params['signature'] = signature

        headers = {
            'Accept': 'application/json',
            'Accept-Encoding': 'UTF-8',
            'Content-Type': 'application/json; charset=UTF-8',
        }

        resp = requests.post(
            urljoin(self.configuration['host'], 'payment/create'), 
            data=json.dumps(params), 
            headers=headers
        )

        data = json.loads(resp.content.decode("utf-8"))

        signature = data.get('signature')
        order_id = data.get('orderId')
        state = data.get('state')
        store_id = data.get('storeId')
        token = data.get('token')

        logger.exception(resp.content.decode("utf-8"))

        if state != 'SUCCESS':
            msg = data.get('message')
            logger.exception(msg)
            raise AuthorizationError(msg)

        sign = self.make_signature(
            state,
            store_id,
            order_id,
            token
        )

        if sign != signature:
            msg = 'Signatures do not match. Payment data has been modified by a third party.'
            logger.exception(msg)
            raise InvalidSignatureError(msg)

        parameters = {
            'token': token,
            'payment_page_url': urljoin(self.configuration['host'], 'payment'),
        }

        return parameters

    def _check_sandbox_required(self, basket):
        sandbox = self.sandbox

        username = basket.owner.username
        #if sandbox or username in ['parhom_999','Ivan','Alena_Sorokina','voyt2365','presli277','banderos1902','agutin_zirochka','john.lennon','ilon.mask.zirochka','super_freddiemercury','salvador_dali_12']:
        if sandbox:
            self.store_id = '4AAD1369CF734B64B70F'
            self.password = '75bef16bfdce4d0e9c0ad5a19b9940df'

    def handle_processor_response(self, response, basket=None):
        """
        Handle a response from the payment processor after callback.

        This method creates PaymentEvents and Sources for successful payments.

        Arguments:
            response (dict): Dictionary of parameters received from the payment processor

        Keyword Arguments:
            basket (Basket): Basket whose contents have been purchased via the payment processor

        Returns:
            HandledProcessorResponse
        """

        self._check_sandbox_required(basket)

        order_id = basket.order_number

        request = {
            "storeId": self.store_id,
            "orderId" : order_id,
        }

        sign = self.make_signature(
            self.store_id,
            basket.order_number,
        )

        request['signature'] = sign

        state_url = urljoin(self.configuration['host'], 'payment/state')

        headers = {
            'Accept': 'application/json',
            'Accept-Encoding': 'UTF-8',
            'Content-Type': 'application/json; charset=UTF-8',
        }

        state_response = requests.post(state_url, data=json.dumps(request), headers=headers)
        data = state_response.content.decode("utf-8")
        response = json.loads(data)

        logger.info(response)

        if 'message' in response:
            message = response.get('message')
        else:
            message = ''

        if 'paymentState' in response:
            payment_state = response.get('paymentState')
        else:
            payment_state = ''

        sign = self.make_signature(
            response.get('state'),
            response.get('storeId'),
            response.get('orderId'),
            payment_state,
            message
        )

        if sign != response.get('signature'):
            msg = 'Signatures do not match. Payment data has been modified by a third party.'
            logger.exception(msg)
            raise InvalidSignatureError(msg)

        transaction_state = response.get('state').lower()

        # Raise an exception for payments that were not accepted.
        if transaction_state not in ('success') or payment_state.lower() not in ('success'):
            msg = 'Status: {status}, message: {err_description}'.format(
                status=transaction_state, err_description=response.get('message')
            )
            logger.error(msg)
            raise GatewayError(msg)

        self.record_processor_response(response, transaction_id=order_id, basket=basket)
        logger.info("Successfully executed PrivatParts payment [%s] for basket [%d].", order_id, basket.id)

        currency = self.currency
        total = Decimal(basket.total_incl_tax)
        label = 'PrivatParts'

        return HandledProcessorResponse(
            transaction_id=order_id,
            total=total,
            currency=currency,
            card_number=label,
            card_type=None
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

        request = {
            "storeId": self.store_id,
            "orderId" : order_number,
            "amount": amount,
        }

        sign = self.make_signature(
            store_id,
            order_id,
            str( int (amount * 100) )
        )

        request['signature'] = sign

        refund_url = urljoin(self.configuration['host'], 'payment/decline')

        headers = {
            'Accept': 'application/json',
            'Accept-Encoding': 'UTF-8',
            'Content-Type': 'application/json; charset=UTF-8',
        }

        refund_response = requests.post(refund_url, data=json.dumps(request), headers=headers)
        response = json.loads(refund_response.content.decode("utf-8"))

        transaction_state = response.get('state').lower()
        transaction_id = reference_number

        ppr = self.record_processor_response(response, transaction_id=transaction_id, basket=basket)

        if transaction_state in ('success'):
            return transaction_id
        else:
            error_message = response.get('message')
            msg = "Failed to refund PrivatParts payment [{transaction_id}] with status [{status}]. " \
                  "PrivatParts's response was recorded in entry [{response_id}].".format(
                      transaction_id=transaction_id, status=error_message, response_id=ppr.id
                  )
            logger.exception(msg)
            raise GatewayError(msg)
