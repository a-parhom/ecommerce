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

class Portmone(BasePaymentProcessor): 
    """Implementation of the Portmone credit card processor"""

    NAME = "portmone"


    def __init__(self, site):
        super(Portmone, self).__init__(site)
        configuration = self.configuration

        self.payee_id = configuration['payee_id']
        self.login = configuration['login']
        self.password = configuration['password']
        self.currency = configuration['currency']
        self.lang = configuration['lang']

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

    def _course_name_from_basket(basket):
        course_name = ''
        for line in basket.all_lines():
            course_name = line.product.title.replace("Seat in ","")
            course_name = course_name.replace(" with professional certificate","")
            break
        return course_name

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

        course_name = self._course_name_from_basket(basket)

        params = {
            "payee_id": self.payee_id,
            "description": u"Оплата онлайн-курсу \"{}\", замовлення {}".format(course_name, basket.order_number),
            "shop_order_number": basket.order_number,
            "bill_currency": self.currency,
            "success_url": urljoin(get_ecommerce_url(), reverse('portmone:result')),
            "failure_url": urljoin(get_ecommerce_url(), reverse('portmone:result')),
            "lang": self.lang,
            "attribute1": self.currency,
            "bill_amount": basket.total_incl_tax,
            'payment_page_url': self.configuration['host'],
        }

        return params


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

        transaction_id = data.get('SHOPBILLID')
        order_id = data.get('SHOPORDERNUMBER')

        #Request additional data from Portmone
        request = {
            "method": "result",
            "params": {
                "data": {  
                    "payee_id": self.configuration['payee_id'],
                    "login": self.configuration['login'],
                    "password": self.configuration['password'],
                    "shop_order_number": order_id
                }
            },
            "id": "1"
        }
        headers = {
            'User-Agent': 'Python SDK',
            'Content-Type': 'application/json',
        }
        additional_data = requests.post(self.configuration['host'], data=json.dumps(request), headers=headers)
        additional_data = json.loads(additional_data.content.decode("utf-8"))

        data.update(additional_data[0])

        transaction_state = data.get('status').lower()

        # Raise an exception for payments that were not accepted.
        if transaction_state not in ('PAYED'):
            error_code = data.get('errorCode')
            error_description = data.get('errorMessage')
            if error_code == '10': #10 - Duplicate transactions
                raise DuplicateReferenceNumber('Order_id [{id}] is duplicated.'.format(id=order_id))
            msg = 'Status: {status}, code: {error_code} - {err_description}'.format(
                status=transaction_state, error_code=error_code, err_description=error_description
            )
            logger.error(msg)
            raise GatewayError(msg)

        self.record_processor_response(data, transaction_id=transaction_id, basket=basket)
        logger.info("Successfully executed Portmone payment [%s] for basket [%d].", transaction_id, basket.id)

        currency = data.get('attribute1')
        total = Decimal(data.get('billAmount'))
        card_number = data.get('cardMask')
        card_type = data.get('gateType')

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

        course_name = self._course_name_from_basket(basket)

        request = {
            "method": "return",
            "params": {
                "data": {
                    "payee_id": self.configuration['payee_id'],
                    "login": self.configuration['login'],
                    "password": self.configuration['password'],
                    "shopbillId": order_number,
                    "returnAmount": amount,
                    "message": "Повернення коштів за онлайн-курс \"{}\"".format(course_name)
                }
            },
            "id": "1"
        }

        refund_url = self.configuration['host']

        headers = {
            'User-Agent': 'Python SDK',
            'Content-Type': 'application/json',
        }

        refund_response = requests.post(refund_url, data=json.dumps(request), headers=headers)
        response = json.loads(refund_response.content.decode("utf-8"))

        transaction_state = response.get('status').lower()
        transaction_id = reference_number

        ppr = self.record_processor_response(response, transaction_id=transaction_id, basket=basket)

        if transaction_state in ('return'):
            return transaction_id
        else:
            error_message = response['error_message']
            msg = "Failed to refund Portmone payment [{transaction_id}] with status [{status}]. " \
                  "Portmone's response was recorded in entry [{response_id}].".format(
                      transaction_id=transaction_id, status=error_message, response_id=ppr.id
                  )
            logger.exception(msg)
            raise GatewayError(msg)
