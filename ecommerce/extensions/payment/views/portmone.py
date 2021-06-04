# -*- coding: utf-8 -*-
""" Views for interacting with the Portmone payment processor. """
from __future__ import unicode_literals

import json
import logging
from base64 import b64decode

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from oscar.apps.partner import strategy
from oscar.apps.payment.exceptions import PaymentError
from oscar.core.loading import get_class, get_model

from ecommerce.extensions.checkout.mixins import EdxOrderPlacementMixin
from ecommerce.extensions.checkout.utils import get_receipt_page_url
from ecommerce.extensions.payment.exceptions import InvalidBasketError
from ecommerce.extensions.payment.processors.portmone import Portmone

logger = logging.getLogger(__name__)

Applicator = get_class('offer.applicator', 'Applicator')
Basket = get_model('basket', 'Basket')
NoShippingRequired = get_class('shipping.methods', 'NoShippingRequired')
Order = get_model('order', 'Order')
OrderNumberGenerator = get_class('order.utils', 'OrderNumberGenerator')
OrderTotalCalculator = get_class('checkout.calculators', 'OrderTotalCalculator')


class PortmonePaymentResultView(EdxOrderPlacementMixin, View):
    """
    Execute an approved Portmone payment and place an order for paid products as appropriate.
    """

    @property
    def payment_processor(self):
        return Portmone(self.request.site)

    # Disable atomicity for the view. Otherwise, we'd be unable to commit to the database
    # until the request had concluded; Django will refuse to commit when an atomic() block
    # is active, since that would break atomicity. Without an order present in the database
    # at the time fulfillment is attempted, asynchronous order fulfillment tasks will fail.
    @method_decorator(transaction.non_atomic_requests)
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super(PortmonePaymentResultView, self).dispatch(request, *args, **kwargs)

    def _get_basket(self, basket_id):
        try:
            basket_id = int(basket_id)
            basket = Basket.objects.get(id=basket_id)
            basket.strategy = strategy.Default()
            Applicator().apply(basket, basket.owner, self.request)
            return basket
        except (ValueError, ObjectDoesNotExist):
            return None

    def create_order(self, request, basket):
        order_number = OrderNumberGenerator().order_number(basket)
        shipping_method = NoShippingRequired()
        shipping_charge = shipping_method.calculate(basket)
        order_total = OrderTotalCalculator().calculate(basket, shipping_charge)
        return self.handle_order_placement(
            order_number=order_number,
            user=basket.owner,
            basket=basket,
            shipping_address=None,
            shipping_method=shipping_method,
            shipping_charge=shipping_charge,
            billing_address=None,
            order_total=order_total,
            request=request
        )

    def post(self, request):
        """
        Handle an incoming user returned to us by Portmone after approving payment.
        """

        portmone_response = request.POST.dict()
        transaction_id = portmone_response.get('SHOPBILLID')
        order_number = portmone_response.get('SHOPORDERNUMBER')
        basket_id = OrderNumberGenerator().basket_id(order_number)
        basket = self._get_basket(basket_id)
        if not basket:
            logger.error(u'Received payment for non-existent basket [%s].', basket_id)
            raise InvalidBasketError
        logger.info(
            u'Received Portmone merchant notification for transaction [%s], associated with basket [%d].',
            transaction_id,
            basket_id
        )

        try:
            with transaction.atomic():
                try:
                    self.handle_payment(portmone_response, basket)
                except PaymentError:
                    logger.exception(u'Portmone payment failed for basket {id}'.format(id=basket.id))
                    return redirect(self.payment_processor.error_url)
        except IntegrityError as e:
            logger.exception(u'Attempts to handle payment for basket {id} failed. Error message: {error}'.format(
                id=basket.id, error=e
            ))
            return redirect(self.payment_processor.error_url)

        receipt_page_url = get_receipt_page_url(
            order_number=basket.order_number,
            site_configuration=basket.site.siteconfiguration
        )

        try:
            order = self.create_order(request, basket)
            return redirect(receipt_page_url)
        except (ValueError, ObjectDoesNotExist, IntegrityError) as e:
            #logger.exception(self.order_placement_failure_msg.encode('utf-8'), basket.id, e)
            logger.exception(u'Order Failure: payment was received, but an order for basket {id} could not be placed. Error message: {error}'.format(
                id=basket.id, error=e
            ))
            return redirect(self.payment_processor.error_url)