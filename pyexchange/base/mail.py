# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import base64


class BaseExchangeMailService(object):
    def __init__(self, service, folder_id):
        self.service = service
        self.folder_id = folder_id


class BaseExchangeMailItem(object):
    _id = None
    _change_key = None
    _service = None
    folder_id = None

    _track_dirty_attributes = False
    _dirty_attributes = set()  # any attributes that have changed, and we need to update in Exchange

    subject = None
    email_address = None
    sender_name = None
    sender_email = None
    from_name = None
    from_email = None
    culture = None
    has_attachments = None
    size = None
    importance = None
    received = None
    # extended properties
    datetime_sent = None
    datetime_created = None
    mimecontent = None  # base64 encoded
    attachments = None
    recipients_to = None
    recipients_cc = None
    recipients_bcc = None
    text_body = None
    html_body = None
    is_read = None

    def __init__(self, service, id=None, xml=None, folder_id=None, **kwargs):
        self.service = service
        self.folder_id = folder_id
        self.attachments = []
        self.recipients_to = []
        self.recipients_cc = []
        self.recipients_bcc = []

        if xml is not None:
            self._init_from_xml(xml)
        elif id is None:
            self._update_properties(kwargs)
        else:
            self._init_from_service(id)

    def _init_from_xml(self, xml):
        raise NotImplementedError

    def _init_from_service(self, id):
        raise NotImplementedError

    @property
    def id(self):
        """ **Read-only.** The internal id Exchange uses to refer to this folder. """
        return self._id

    @property
    def change_key(self):
        """ **Read-only.** When you change a contact, Exchange makes you pass a change key to prevent overwriting a previous version. """
        return self._change_key

    def _update_properties(self, properties):
        self._track_dirty_attributes = False
        for key in properties:
            setattr(self, key, properties[key])
        self._track_dirty_attributes = True

    def __setattr__(self, key, value):
        """ Magically track public attributes, so we can track what we need to flush to the Exchange store """
        if self._track_dirty_attributes and not key.startswith(u"_"):
            self._dirty_attributes.add(key)

        object.__setattr__(self, key, value)

    def _reset_dirty_attributes(self):
        self._dirty_attributes = set()

    def _format_email_address(self, name, email):
        if name and email:
            return "{} <{}>".format(name, email)
        return name or email

    @property
    def sender(self):
        from_ = self._format_email_address(self.from_name, self.from_email)
        if not from_:
            from_ = self._format_email_address(self.sender_name,
                                               self.sender_email)
        return from_

    @property
    def body(self):
        return base64.b64decode(self.mimecontent)
