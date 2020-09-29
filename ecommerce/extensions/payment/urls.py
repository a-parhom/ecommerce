from django.conf.urls import include, url

from ecommerce.extensions.payment.views import PaymentFailedView, SDNFailure, cybersource, paypal, liqpay, fondy, portmone

CYBERSOURCE_URLS = [
    url(r'^redirect/$', cybersource.CybersourceInterstitialView.as_view(), name='redirect'),
    url(r'^submit/$', cybersource.CybersourceSubmitView.as_view(), name='submit'),
]

PAYPAL_URLS = [
    url(r'^execute/$', paypal.PaypalPaymentExecutionView.as_view(), name='execute'),
    url(r'^profiles/$', paypal.PaypalProfileAdminView.as_view(), name='profiles'),
]

SDN_URLS = [
    url(r'^failure/$', SDNFailure.as_view(), name='failure'),
]

LIQPAY_URLS = [
    url(r'^callback/$', liqpay.LiqpayPaymentCallbackView.as_view(), name='callback'),
    url(r'^processed/$', liqpay.LiqpayPaymentProcessedView.as_view(), name='processed'),
]

FONDY_URLS = [
    url(r'^result/$', fondy.FondyPaymentResultView.as_view(), name='result'),
]

PORTMONE_URLS = [
    url(r'^result/$', portmone.PortmonePaymentResultView.as_view(), name='result'),
]

urlpatterns = [
    url(r'^cybersource/', include(CYBERSOURCE_URLS, namespace='cybersource')),
    url(r'^error/$', PaymentFailedView.as_view(), name='payment_error'),
    url(r'^paypal/', include(PAYPAL_URLS, namespace='paypal')),
    url(r'^sdn/', include(SDN_URLS, namespace='sdn')),
    url(r'^liqpay/', include(LIQPAY_URLS, namespace='liqpay')),
    url(r'^fondy/', include(FONDY_URLS, namespace='fondy')),
    url(r'^portmone/', include(PORTMONE_URLS, namespace='portmone'))
]
