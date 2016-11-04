class BaseExchangeTaskService(object):
    def __init__(self, service, folder_id):
        self.service = service
        self.folder_id = folder_id

    def get_task(self, id):
        raise NotImplementedError

    def new_task(self, **properties):
        raise NotImplementedError


class BaseExchangeTaskItem(object):
    _id = None
    _change_key = None

    _service = None
    folder_id = None

    _track_dirty_attributes = False
    _dirty_attributes = set()  # any attributes that have changed, and we need to update in Exchange

    subject = None
    text_body = None
    html_body = None
    categories = None
    is_draft = None
    sent_at = None
    created_at = None
    due_date = None
    recurrence = None
    is_complete = None
    owner = None
    start_date = None
    complete_date = None
    status = None
    status_description = None
    percent_complete = None
    importance = None
    companies = None
    last_modified_by = None
    last_modified_at = None

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
