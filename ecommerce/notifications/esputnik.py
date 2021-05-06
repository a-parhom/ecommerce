# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import json
import logging
import requests
import json
import urllib
from django.conf import settings

logger = logging.getLogger(__name__)

class ESputnikAPI(object):

	def __init__(self):
		self.api_key = settings.ESPUTNIK_API_KEY

		self.oauth2_issuer = settings.BACKEND_SERVICE_EDX_OAUTH2_PROVIDER_URL
		self.oauth2_client_id = settings.BACKEND_SERVICE_EDX_OAUTH2_KEY
		self.oauth2_client_secret = settings.BACKEND_SERVICE_EDX_OAUTH2_SECRET

	def _get_auth_headers(self):
		url = "/access_token"

		response = requests.post(
			self.oauth2_issuer + url,
			data={
				'grant_type': 'client_credentials',
				'token_type': 'bearer',
				'client_id': self.oauth2_client_id,
				'client_secret': self.oauth2_client_secret
			}
		)
		print(response.content)
		response = json.loads(response.content.decode('utf-8'))

		token = "Bearer {token}".format(token=response['access_token'])
		headers = {'Authorization': token}
		return headers

	def _get_user_details(self, user):
		url = 'https://courses.prometheus.org.ua/api/user/v1/accounts/'

		username = user.username

		response = requests.get(
			url + username, 
			headers=self._get_auth_headers()
		)

		return json.loads(response.content.decode('utf-8'))

	def _make_request(self, url, data, method="POST"):
		headers = {
			'Accept': 'application/json',
			'Content-Type': 'application/json',
		}

		if method == "GET":
			url += "?"+urllib.parse.urlencode(data, True)
			data = {}

		response = requests.request(
			method,
			url, 
			data=data, 
			headers=headers,
			auth=('eSputnik', self.api_key)
		)

		return response.content.decode('utf-8')

	def send_email(self, user, messages, site=None, recipient=None):
		if not (recipient or user.email):
			msg = "Unable to send eSputnik email messages: No email address for '{username}'.".format(username=user.username)
			self.logger.warning(msg)
			return

		recipient = recipient if recipient else user.email

		from_email = settings.OSCAR_FROM_EMAIL
		if site:
			from_email = site.siteconfiguration.get_from_email()

		data = {
			'from': from_email,
			'subject': messages['subject'],
			'htmlText': messages['html'],
			'plainText': messages['body'],
			'emails': [recipient]
		}

		url = 'https://esputnik.com/api/v1/message/email'

		self.logger.info("Sending eSputnik email to %s", recipient)

		self._make_request(url, data, method="POST")

	def find_by_email(self, email=None, user=None):
		if not (email or user.email):
			msg = "Unable to find eSputnik contact by email: No email address for '{username}'.".format(username=user.username)
			self.logger.warning(msg)
			return

		email = email if email else user.email
		print(email)

		data = {'email': email}

		url = 'https://esputnik.com/api/v1/contacts'

		return self._make_request(url, data, method="GET")

	def create_order(self, user, order):
		email = user.email
		data = {
			'eventTypeKey': 'orderCreated',
			'keyValue': email,
			'params': [
				{
					"name": "externalOrderId",
					"value": orderId
				},
				{
					"name": "externalCustomerId",
					"value": user.lms_user_id
				},
				{
					"name": "totalCost",
					"value": totalCost
				},
				{
					"name": "status",
					"value": "INITIALIZED"
				},
				{
					"name": "date",
					"value": orderDate
				},
				{
					"name": "email",
					"value": email
				},
				{
					"name": "email",
					"value": phone
				},
				{	
					"name": "items",
					"value": [
						{
							"externalItemId": course_id,
							"name": course_name,
							"category": "",
							"quantity": 1,
							"cost": totalCost,
							"url": ""
						}
					]
				}
			]
		}
		url = 'v1/event'
		return self._make_request(url, data, method="post")

	def update_order(self, user, order):
		email = user.email
		data = {
			'eventTypeKey': 'orderUpdated',
			'keyValue': email,
			'params': [
				{
					"name": "externalOrderId",
					"value": orderId
				},
				{
					"name": "externalCustomerId",
					"value": user.lms_user_id
				},
				{
					"name": "status",
					"value": "INITIALIZED"
				},
				{
					"name": "email",
					"value": email
				},
			]
		}
		url = 'v1/event'
		return self._make_request(url, data, method="post")
