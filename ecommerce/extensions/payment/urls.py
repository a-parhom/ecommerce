from __future__ import absolute_import

from django.conf.urls import include, url

from ecommerce.extensions.payment.views import PaymentFailedView, SDNFailure, cybersource, paypal, stripe, liqpay, fondy, portmone, privatparts

CYBERSOURCE_APPLE_PAY_URLS = [
    url(r'^authorize/$', cybersource.CybersourceApplePayAuthorizationView.as_view(), name='authorize'),
    url(r'^start-session/$', cybersource.ApplePayStartSessionView.as_view(), name='start_session'),
]
CYBERSOURCE_URLS = [
    url(r'^apple-pay/', include((CYBERSOURCE_APPLE_PAY_URLS, 'apple_pay'))),
    url(r'^redirect/$', cybersource.CybersourceInterstitialView.as_view(), name='redirect'),
    url(r'^submit/$', cybersource.CybersourceSubmitView.as_view(), name='submit'),
    url(r'^api-submit/$', cybersource.CybersourceSubmitAPIView.as_view(), name='api_submit'),
]

PAYPAL_URLS = [
    url(r'^execute/$', paypal.PaypalPaymentExecutionView.as_view(), name='execute'),
    url(r'^profiles/$', paypal.PaypalProfileAdminView.as_view(), name='profiles'),
]

SDN_URLS = [
    url(r'^failure/$', SDNFailure.as_view(), name='failure'),
]

STRIPE_URLS = [
    url(r'^submit/$', stripe.StripeSubmitView.as_view(), name='submit'),
]

LIQPAY_URLS = [
    url(r'^callback/$', liqpay.LiqpayPaymentCallbackView.as_view(), name='callback'),
    url(r'^processed/$', liqpay.LiqpayPaymentProcessedView.as_view(), name='processed'),
]

PRIVATPARTS_URLS = [
    url(r'^callback/$', privatparts.PrivatpartsPaymentCallbackView.as_view(), name='callback'),
    url(r'^processed/$', privatparts.PrivatpartsPaymentProcessedView.as_view(), name='processed'),
]

FONDY_URLS = [
    url(r'^result/$', fondy.FondyPaymentResultView.as_view(), name='result'),
]

PORTMONE_URLS = [
    url(r'^result/$', portmone.PortmonePaymentResultView.as_view(), name='result'),
]

urlpatterns = [
    url(r'^cybersource/', include((CYBERSOURCE_URLS, 'cybersource'))),
    url(r'^error/$', PaymentFailedView.as_view(), name='payment_error'),
    url(r'^paypal/', include((PAYPAL_URLS, 'paypal'))),
    url(r'^sdn/', include((SDN_URLS, 'sdn'))),
    url(r'^stripe/', include((STRIPE_URLS, 'stripe'))),
    url(r'^liqpay/', include((LIQPAY_URLS, 'liqpay'))),
    url(r'^privatparts/', include((PRIVATPARTS_URLS, 'privatparts'))),
    url(r'^fondy/', include((FONDY_URLS, 'fondy'))),
    url(r'^portmone/', include((PORTMONE_URLS, 'portmone')))
]
