# -*- coding: utf-8 -*-
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
    attachments = []
    recipients_to = []
    recipients_cc = []

    @property
    def sender(self):
        if self.from_name is None or self.from_email is None:
            return u'%s <%s>' % (self.sender_name, self.sender_email)
        else:
            return u'%s <%s>' % (self.from_name, self.from_email)

    @property
    def body(self):
        return base64.b64decode(self.mimecontent)

    def __init__(self, service, id=None, xml=None, folder_id=None, **kwargs):
        self.service = service
        self.folder_id = folder_id

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

