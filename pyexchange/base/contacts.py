class BaseExchangeContactService(object):
    def __init__(self, service, folder_id):
        self.service = service
        self.folder_id = folder_id

    def get_contact(self, id):
        raise NotImplementedError

    def new_contact(self, **properties):
        raise NotImplementedError


class BaseExchangeContactItem(object):
    _id = None
    _change_key = None

    _service = None
    folder_id = None

    _track_dirty_attributes = False
    _dirty_attributes = set()  # any attributes that have changed, and we need to update in Exchange

    first_name = None
    last_name = None
    full_name = None
    display_name = None
    sort_name = None
    email_address1 = None
    email_address2 = None
    email_address3 = None
    birthday = None
    job_title = None
    department = None
    company_name = None
    office_location = None
    primary_phone = None
    business_phone = None
    home_phone = None
    mobile_phone = None

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

    def create(self):
        raise NotImplementedError

    def update(self):
        raise NotImplementedError

    def delete(self):
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

    def validate(self):
        """ Validates that all required fields are present """
        if not self.display_name:
            raise ValueError("Folder has no display_name")

        if not self.parent_id:
            raise ValueError("Folder has no parent_id")
