class BaseExchangeRoomService(object):
    def __init__(self, service):
        self.service = service


class BaseExchangeRoomItem(object):
    _id = None
    _change_key = None

    _service = None
