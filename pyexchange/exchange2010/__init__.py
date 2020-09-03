"""
(c) 2013 LinkedIn Corp. All rights reserved.
Licensed under the Apache License, Version 2.0 (the "License");?you may not use this file except in compliance with the License. You may obtain a copy of the License at  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software?distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
"""
from __future__ import unicode_literals

import logging
from ..base.calendar import BaseExchangeCalendarEvent, BaseExchangeCalendarService, ExchangeEventOrganizer, \
    ExchangeEventResponse, ExchangeExtendedProperty
from ..base.contacts import BaseExchangeContactService, BaseExchangeContactItem
from ..base.rooms import BaseExchangeRoomService, BaseExchangeRoomItem
from ..base.folder import BaseExchangeFolder, BaseExchangeFolderService
from ..base.mail import BaseExchangeMailService, BaseExchangeMailItem
from ..base.tasks import BaseExchangeTaskService, BaseExchangeTaskItem
from ..base.soap import ExchangeServiceSOAP, S
from ..exceptions import FailedExchangeException, ExchangeStaleChangeKeyException, ExchangeItemNotFoundException, ExchangeInternalServerTransientErrorException, ExchangeIrresolvableConflictException, InvalidEventType
from ..compat import BASESTRING_TYPES

from . import soap_request

from lxml import etree
from copy import deepcopy
from collections import namedtuple
from datetime import date
import warnings
import email
import six

log = logging.getLogger("pyexchange")


NotificationSubscription = namedtuple('NotificationSubscription',
                                      'id watermark')


class Exchange2010Service(ExchangeServiceSOAP):
    def __init__(self, connection, batch_size=1000, impersonate_sid=None, impersonate_smtp=None):
        super(Exchange2010Service, self).__init__(connection)
        # The size of batches requested for paginated result sets.
        self.batch_size = batch_size
        self.impersonate_sid = impersonate_sid
        self.impersonate_smtp = impersonate_smtp

    def calendar(self, id="calendar"):
        return Exchange2010CalendarService(service=self, calendar_id=id)

    def contacts(self, folder_id="contacts"):
        return Exchange2010ContactService(service=self, folder_id=folder_id)

    def rooms(self):
        return Exchange2010RoomService(service=self)

    def folder(self):
        return Exchange2010FolderService(service=self)

    def mail(self, folder_id="inbox"):
        return Exchange2010MailService(service=self, folder_id=folder_id)

    def tasks(self, folder_id="tasks"):
        return Exchange2010TaskService(service=self, folder_id=folder_id)

    def notifications(self):
        return Exchange2010NotificationService(self)

    def convert_id(self, from_id, destination_format, format='EwsId',
                   mailbox='a@b.com'):
        body = soap_request.convert_id(from_id, destination_format,
                                       format, mailbox)
        response = self.send(body)
        return response.xpath(u'//m:ConvertIdResponseMessage/m:AlternateId/@Id',
                              namespaces=soap_request.NAMESPACES)

    def _send_soap_request(self, body, headers=None, retries=2, timeout=30, encoding="utf-8"):
        headers = {
            "Accept": "text/xml",
            "Content-type": "text/xml; charset=%s " % encoding
        }
        return super(Exchange2010Service, self)._send_soap_request(body, headers=headers, retries=retries, timeout=timeout, encoding=encoding)

    def _wrap_soap_xml_request(self, exchange_xml):
        header = S.Header(
            soap_request.T.RequestServerVersion(
                Version="Exchange2010",
            ),
        )
        if self.impersonate_sid or self.impersonate_smtp:
            if self.impersonate_smtp:
                impersonate = soap_request.T.PrimarySmtpAddress(self.impersonate_smtp)
            else:
                impersonate = soap_request.T.SID(self.impersonate_sid)

            header.append(
                soap_request.T.ExchangeImpersonation(
                    soap_request.T.ConnectingSID(
                        impersonate,
                    ),
                ),
            )
        return S.Envelope(
            header,
            S.Body(exchange_xml),
        )

    def _check_for_errors(self, xml_tree):
        super(Exchange2010Service, self)._check_for_errors(xml_tree)
        self._check_for_exchange_fault(xml_tree)

    def _check_for_exchange_fault(self, xml_tree):

        # If the request succeeded, we should see a <m:ResponseCode>NoError</m:ResponseCode>
        # somewhere in the response. if we don't (a) see the tag or (b) it doesn't say "NoError"
        # then flip out

        response_codes = xml_tree.xpath(u'//m:ResponseCode', namespaces=soap_request.NAMESPACES)

        if not response_codes:
            raise FailedExchangeException(u"Exchange server did not return a status response", None)

        # The full (massive) list of possible return responses is here.
        # http://msdn.microsoft.com/en-us/library/aa580757(v=exchg.140).aspx
        for code in response_codes:
            if code.text == u"ErrorChangeKeyRequiredForWriteOperations":
                # change key is missing or stale. we can fix that, so throw a special error
                raise ExchangeStaleChangeKeyException(u"Exchange Fault (%s) from Exchange server" % code.text)
            elif code.text == u"ErrorItemNotFound":
                # exchange_invite_key wasn't found on the server
                raise ExchangeItemNotFoundException(u"Exchange Fault (%s) from Exchange server" % code.text)
            elif code.text == u"ErrorIrresolvableConflict":
                # tried to update an item with an old change key
                raise ExchangeIrresolvableConflictException(u"Exchange Fault (%s) from Exchange server" % code.text)
            elif code.text == u"ErrorInternalServerTransientError":
                # temporary internal server error. throw a special error so we can retry
                raise ExchangeInternalServerTransientErrorException(u"Exchange Fault (%s) from Exchange server" % code.text)
            elif code.text == u"ErrorCalendarOccurrenceIndexIsOutOfRecurrenceRange":
                # just means some or all of the requested instances are out of range
                pass
            elif code.text != u"NoError":
                raise FailedExchangeException(u"Exchange Fault (%s) from Exchange server" % code.text)


class Exchange2010CalendarService(BaseExchangeCalendarService):
    def folders(self):
        return

    def event(self, id=None, **kwargs):
        return Exchange2010CalendarEvent(service=self.service, id=id, **kwargs)

    def get_event(self, id, additional_properties=None):
        return Exchange2010CalendarEvent(service=self.service, id=id, additional_properties=additional_properties)

    def new_event(self, **properties):
        return Exchange2010CalendarEvent(service=self.service, calendar_id=self.calendar_id, **properties)

    def list_events(self, start=None, end=None, details=False, delegate_for=None, additional_properties=None):
        return Exchange2010CalendarEventList(service=self.service, calendar_id=self.calendar_id, start=start, end=end,
                                             details=details, delegate_for=delegate_for,
                                             additional_properties=additional_properties)

    def sync_events(self, delegate_for=None, sync_state=None):
        return Exchange2010SyncCalendarEventList(service=self.service, calendar_id=self.calendar_id,
                                                 delegate_for=delegate_for, sync_state=sync_state)

    def get_user_availability(self, attendees, start, end):
        return Exchange2010UserAvailabilityList(self.service, attendees, start, end)


class Exchange2010UserAvailabilityList(object):
    def __init__(self, service, attendees, start, end):
        self.service = service
        self.attendees = attendees
        body = soap_request.get_user_availability(attendees or [], start, end)

        response_xml = self.service.send(body, check_for_errors=False)

        self._parse_response_for_results(response_xml)

    def _parse_response_for_results(self, response):
        for i, free_busy_view in enumerate(response.xpath(
                '//m:GetUserAvailabilityResponse/m:FreeBusyResponseArray/m:FreeBusyResponse/m:FreeBusyView',
                namespaces=soap_request.NAMESPACES)):

            self.attendees[i]['busy'] = []

            for calendar_event in free_busy_view.xpath('t:CalendarEventArray/t:CalendarEvent',
                                                       namespaces=soap_request.NAMESPACES):

                self.attendees[i]['busy'].append(dict(
                    start_time=calendar_event.findtext('t:StartTime', namespaces=soap_request.NAMESPACES),
                    end_time=calendar_event.findtext('t:EndTime', namespaces=soap_request.NAMESPACES),
                    busy_type=calendar_event.findtext('t:BusyType', namespaces=soap_request.NAMESPACES),
                ))


class Exchange2010SyncCalendarEventList(object):
    def __init__(self, service=None, calendar_id='calendar', delegate_for=None, sync_state=None):
        self.service = service
        self.delegate_for = delegate_for

        self.created = []
        self.updated = []
        self.deleted = []
        self.last_sync_state = None

        body = soap_request.sync_calendar_items(
            calendar_id=calendar_id, delegate_for=delegate_for, sync_state=sync_state
        )

        response_xml = self.service.send(body)

        self._parse_response_for_all_events(response_xml)
        self.contains_all_items = "true" == response_xml.xpath(
            '//m:SyncFolderItemsResponseMessage/m:IncludesLastItemInRange',
            namespaces=soap_request.NAMESPACES,
        )[0].text

        self.last_sync_state = response_xml.xpath(
            '//m:SyncFolderItemsResponseMessage/m:SyncState',
            namespaces=soap_request.NAMESPACES,
        )[0].text

    def _parse_response_for_all_events(self, response):
        changes = response.xpath('//m:SyncFolderItemsResponseMessage/m:Changes', namespaces=soap_request.NAMESPACES)[0]

        for create in changes.xpath('//t:Create/t:CalendarItem', namespaces=soap_request.NAMESPACES):
            self.created.append(Exchange2010CalendarEvent(service=self.service,
                                                          xml=soap_request.M.Items(deepcopy(create))))

        for update in changes.xpath('//t:Update/t:CalendarItem', namespaces=soap_request.NAMESPACES):
            self.updated.append(Exchange2010CalendarEvent(service=self.service,
                                                          xml=soap_request.M.Items(deepcopy(update))))

        for delete in changes.xpath('//t:Delete/t:ItemId/@Id', namespaces=soap_request.NAMESPACES):
            self.deleted.append(delete)

        return self


class Exchange2010CalendarEventList(object):
    """
    Creates & Stores a list of Exchange2010CalendarEvent items in the "self.events" variable.
    """

    def __init__(self, service=None, calendar_id=u'calendar', start=None, end=None, details=False, delegate_for=None,
                 additional_properties=None):
        self.service = service
        self.count = 0
        self.start = start
        self.end = end
        self.events = list()
        self.event_ids = list()
        self.details = details
        self.delegate_for = delegate_for
        self.total_items_in_view = None
        self.contains_all_items = None

        # This request uses a Calendar-specific query between two dates.
        body = soap_request.get_calendar_items(
            format=u'AllProperties', calendar_id=calendar_id,
            start=self.start, end=self.end, delegate_for=self.delegate_for,
            max_entries=1000, additional_properties=additional_properties
        )
        response_xml = self.service.send(body)
        self._parse_response_for_all_events(response_xml)
        self.contains_all_items = "true" == response_xml.xpath(
            '//m:RootFolder/@IncludesLastItemInRange',
            namespaces=soap_request.NAMESPACES,
        )[0]
        self.total_items_in_view = int(response_xml.xpath(
            '//m:RootFolder/@TotalItemsInView',
            namespaces=soap_request.NAMESPACES,
        )[0])

        # Populate the event ID list, for convenience reasons.
        for event in self.events:
            self.event_ids.append(event._id)

        # If we have requested all the details, basically repeat the previous 3 steps,
        # but instead of start/stop, we have a list of ID fields.
        if self.details:
            log.debug(u'Received request for all details, retrieving now!')
            self.load_all_details()
        return

    def _parse_response_for_all_events(self, response):
        """
        This function will retrieve *most* of the event data, excluding Organizer & Attendee details
        """
        items = response.xpath(u'//m:FindItemResponseMessage/m:RootFolder/t:Items/t:CalendarItem', namespaces=soap_request.NAMESPACES)
        if not items:
            items = response.xpath(u'//m:GetItemResponseMessage/m:Items/t:CalendarItem', namespaces=soap_request.NAMESPACES)
        if items:
            self.count = len(items)
            log.debug(u'Found %s items' % self.count)

            for item in items:
                self._add_event(xml=soap_request.M.Items(deepcopy(item)))
        else:
            log.debug(u'No calendar items found with search parameters.')

        return self

    def _add_event(self, xml=None):
        log.debug(u'Adding new event to all events list.')
        event = Exchange2010CalendarEvent(service=self.service, xml=xml)
        log.debug(u'Subject of new event is %s' % event.subject)
        self.events.append(event)
        return self

    def load_all_details(self):
        """
        This function will execute all the event lookups for known events.

        This is intended for use when you want to have a completely populated event entry, including
        Organizer & Attendee details.
        """
        log.debug(u"Loading all details")
        if self.count > 0:
            # Now, empty out the events to prevent duplicates!
            del(self.events[:])

            # Send the SOAP request with the list of exchange ID values.
            log.debug(u"Requesting all event details for events: {event_list}".format(event_list=str(self.event_ids)))
            body = soap_request.get_item(exchange_id=self.event_ids, format=u'AllProperties')
            response_xml = self.service.send(body)

            # Re-parse the results for all the details!
            self._parse_response_for_all_events(response_xml)

        return self


class Exchange2010CalendarEvent(BaseExchangeCalendarEvent):

    def _init_from_service(self, id, additional_properties=None):
        log.debug(u'Creating new Exchange2010CalendarEvent object from ID')
        body = soap_request.get_item(exchange_id=id, format=u'AllProperties',
                                     additional_properties=additional_properties)
        response_xml = self.service.send(body)
        properties = self._parse_response_for_get_event(response_xml)

        self._update_properties(properties)
        self._id = id
        log.debug(u'Created new event object with ID: %s' % self._id)

        self._reset_dirty_attributes()

        return self

    def _init_from_xml(self, xml=None):
        log.debug(u'Creating new Exchange2010CalendarEvent object from XML')

        properties = self._parse_response_for_get_event(xml)
        self._update_properties(properties)
        self._id, self._change_key = self._parse_id_and_change_key_from_response(xml)

        log.debug(u'Created new event object with ID: %s' % self._id)
        self._reset_dirty_attributes()

        return self

    def as_json(self):
        raise NotImplementedError

    def validate(self):

        if self.recurrence is not None:

            if not (isinstance(self.recurrence_end_date, date)):
                raise ValueError('recurrence_end_date must be of type date')
            elif (self.recurrence_end_date < self.start.date()):
                raise ValueError('recurrence_end_date must be after start')

            if self.recurrence == u'daily':

                if not (isinstance(self.recurrence_interval, int) and 1 <= self.recurrence_interval <= 999):
                    raise ValueError('recurrence_interval must be an int in the range from 1 to 999')

            elif self.recurrence == u'weekly':

                if not (isinstance(self.recurrence_interval, int) and 1 <= self.recurrence_interval <= 99):
                    raise ValueError('recurrence_interval must be an int in the range from 1 to 99')

                if self.recurrence_days is None:
                    raise ValueError('recurrence_days is required')
                for day in self.recurrence_days.split(' '):
                    if day not in self.WEEKLY_DAYS:
                        raise ValueError('recurrence_days received unknown value: %s' % day)

            elif self.recurrence == u'monthly':

                if not (isinstance(self.recurrence_interval, int) and 1 <= self.recurrence_interval <= 99):
                    raise ValueError('recurrence_interval must be an int in the range from 1 to 99')

            elif self.recurrence == u'yearly':

                pass  # everything is pulled from start

            else:

                raise ValueError('recurrence received unknown value: %s' % self.recurrence)

        super(Exchange2010CalendarEvent, self).validate()

    def create(self):
        """
        Creates an event in Exchange. ::

            event = service.calendar().new_event(
              subject=u"80s Movie Night",
              location = u"My house",
            )
            event.create()

        Invitations to attendees are sent out immediately.

        """
        self.validate()
        body = soap_request.new_event(self)

        response_xml = self.service.send(body)
        self._id, self._change_key = self._parse_id_and_change_key_from_response(response_xml)

        return self

    def resend_invitations(self):
        """
        Resends invites for an event.  ::

            event = service.calendar().get_event(id='KEY HERE')
            event.resend_invitations()

        Anybody who has not declined this meeting will get a new invite.
        """

        if not self.id:
            raise TypeError(u"You can't send invites for an event that hasn't been created yet.")

        # Under the hood, this is just an .update() but with no attributes changed.
        # We're going to enforce that by checking if there are any changed attributes and bail if there are
        if self._dirty_attributes:
            raise ValueError(u"There are unsaved changes to this invite - please update it first: %r" % self._dirty_attributes)

        self.refresh_change_key()
        body = soap_request.update_item(self, [], calendar_item_update_operation_type=u'SendOnlyToAll')
        self.service.send(body)

        return self

    def update(self, calendar_item_update_operation_type=u'SendToAllAndSaveCopy', **kwargs):
        """
        Updates an event in Exchange.  ::

            event = service.calendar().get_event(id='KEY HERE')
            event.location = u'New location'
            event.update()

        If no changes to the event have been made, this method does nothing.

        Notification of the change event is sent to all users. If you wish to just notify people who were
        added, specify ``send_only_to_changed_attendees=True``.
        """
        if not self.id:
            raise TypeError(u"You can't update an event that hasn't been created yet.")

        if 'send_only_to_changed_attendees' in kwargs:
            warnings.warn(
                "The argument send_only_to_changed_attendees is deprecated.  Use calendar_item_update_operation_type instead.",
                DeprecationWarning,
                )  # 20140502
            if kwargs['send_only_to_changed_attendees']:
                calendar_item_update_operation_type = u'SendToChangedAndSaveCopy'

        VALID_UPDATE_OPERATION_TYPES = (
            u'SendToNone', u'SendOnlyToAll', u'SendOnlyToChanged',
            u'SendToAllAndSaveCopy', u'SendToChangedAndSaveCopy',
        )
        if calendar_item_update_operation_type not in VALID_UPDATE_OPERATION_TYPES:
            raise ValueError('calendar_item_update_operation_type has unknown value')

        self.validate()

        if self._dirty_attributes:
            log.debug(u"Updating these attributes: %r" % self._dirty_attributes)
            self.refresh_change_key()

            body = soap_request.update_item(self, self._dirty_attributes, calendar_item_update_operation_type=calendar_item_update_operation_type)
            self.service.send(body)
            self._reset_dirty_attributes()
        else:
            log.info(u"Update was called, but there's nothing to update. Doing nothing.")

        return self

    def cancel(self):
        """
        Cancels an event in Exchange.  ::

            event = service.calendar().get_event(id='KEY HERE')
            event.cancel()

        This will send notifications to anyone who has not declined the meeting.
        """
        if not self.id:
            raise TypeError(u"You can't delete an event that hasn't been created yet.")

        self.refresh_change_key()
        self.service.send(soap_request.delete_event(self))
        # TODO rsanders high - check return status to make sure it was actually sent
        return None

    def move_to(self, folder_id):
        """
        :param str folder_id: The Calendar ID to where you want to move the event to.
        Moves an event to a different folder (calendar).  ::

          event = service.calendar().get_event(id='KEY HERE')
          event.move_to(folder_id='NEW CALENDAR KEY HERE')
        """
        if not folder_id:
            raise TypeError(u"You can't move an event to a non-existant folder")

        if not isinstance(folder_id, BASESTRING_TYPES):
            raise TypeError(u"folder_id must be a string")

        if not self.id:
            raise TypeError(u"You can't move an event that hasn't been created yet.")

        self.refresh_change_key()
        response_xml = self.service.send(soap_request.move_event(self, folder_id))
        new_id, new_change_key = self._parse_id_and_change_key_from_response(response_xml)
        if not new_id:
            raise ValueError(u"MoveItem returned success but requested item not moved")

        self._id = new_id
        self._change_key = new_change_key
        self.calendar_id = folder_id
        return self

    def get_master(self):
        """
          get_master()
          :raises InvalidEventType: When this method is called on an event that is not a Occurrence type.

          This will return the master event to the occurrence.

          **Examples**::

            event = service.calendar().get_event(id='<event_id>')
            print event.type  # If it prints out 'Occurrence' then that means we could get the master.

            master = event.get_master()
            print master.type  # Will print out 'RecurringMaster'.


        """

        if self.type not in ['Occurrence', 'Exception']:
            raise InvalidEventType("get_master method can only be called on a 'Occurrence' or 'Exception' event type, '{}' received".format(self.type))

        body = soap_request.get_master(exchange_id=self._id, format=u"AllProperties")
        response_xml = self.service.send(body)

        return Exchange2010CalendarEvent(service=self.service, xml=response_xml)

    def get_occurrence(self, instance_index):
        """
          get_occurrence(instance_index)
          :param iterable instance_index: This should be tuple or list of integers which correspond to occurrences.
          :raises TypeError: When instance_index is not an iterable of ints.
          :raises InvalidEventType: When this method is called on an event that is not a RecurringMaster type.

          This will return a list of occurrence events.

          **Examples**::

            master = service.calendar().get_event(id='<event_id>')

            # The following will return the first 20 occurrences in the recurrence.
            # If there are not 20 occurrences, it will only return what it finds.
            occurrences = master.get_occurrence(range(1,21))
            for occurrence in occurrences:
              print occurrence.start

        """

        if not all([isinstance(i, int) for i in instance_index]):
            raise TypeError("instance_index must be an interable of type int")

        if self.type != 'RecurringMaster':
            raise InvalidEventType("get_occurrance method can only be called on a 'RecurringMaster' event type")

        body = soap_request.get_occurrence(exchange_id=self._id, instance_index=instance_index, format=u"AllProperties")
        response_xml = self.service.send(body)

        items = response_xml.xpath(u'//m:GetItemResponseMessage/m:Items', namespaces=soap_request.NAMESPACES)
        events = []
        for item in items:
            event = Exchange2010CalendarEvent(service=self.service, xml=deepcopy(item))
            if event.id:
                events.append(event)

        return events

    def conflicting_events(self):
        """
          conflicting_events()

          This will return a list of conflicting events.

          **Example**::

            event = service.calendar().get_event(id='<event_id>')
            for conflict in event.conflicting_events():
              print conflict.subject

        """

        if not self.conflicting_event_ids:
            return []

        body = soap_request.get_item(exchange_id=self.conflicting_event_ids, format="AllProperties")
        response_xml = self.service.send(body)

        items = response_xml.xpath(u'//m:GetItemResponseMessage/m:Items', namespaces=soap_request.NAMESPACES)
        events = []
        for item in items:
            event = Exchange2010CalendarEvent(service=self.service, xml=deepcopy(item))
            if event.id:
                events.append(event)

        return events

    def refresh_change_key(self):

        body = soap_request.get_item(exchange_id=self._id, format=u"IdOnly")
        response_xml = self.service.send(body)
        self._id, self._change_key = self._parse_id_and_change_key_from_response(response_xml)

        return self

    def _parse_id_and_change_key_from_response(self, response):

        id_elements = response.xpath(u'//m:Items/t:CalendarItem/t:ItemId', namespaces=soap_request.NAMESPACES)

        if id_elements:
            id_element = id_elements[0]
            return id_element.get(u"Id", None), id_element.get(u"ChangeKey", None)
        else:
            return None, None

    def _parse_response_for_get_event(self, response):
        result = self._parse_event_properties(response)

        organizer_properties = self._parse_event_organizer(response)
        if organizer_properties is not None:
            if 'email' not in organizer_properties:
                organizer_properties['email'] = None
            result[u'organizer'] = ExchangeEventOrganizer(**organizer_properties)

        attendee_properties = self._parse_event_attendees(response)
        result[u'_attendees'] = self._build_resource_dictionary([ExchangeEventResponse(**attendee) for attendee in attendee_properties])

        resource_properties = self._parse_event_resources(response)
        result[u'_resources'] = self._build_resource_dictionary([ExchangeEventResponse(**resource) for resource in resource_properties])

        result['_conflicting_event_ids'] = self._parse_event_conflicts(response)

        self.xml = response

        return result

    def _parse_event_properties(self, response):

        property_map = {
            u'subject': {
                u'xpath': u'//m:Items/t:CalendarItem/t:Subject',
            },
            u'location': {
                u'xpath': u'//m:Items/t:CalendarItem/t:Location',
            },
            u'availability': {
                u'xpath': u'//m:Items/t:CalendarItem/t:LegacyFreeBusyStatus',
            },
            u'start': {
                u'xpath': u'//m:Items/t:CalendarItem/t:Start',
                u'cast': u'datetime',
            },
            u'end': {
                u'xpath': u'//m:Items/t:CalendarItem/t:End',
                u'cast': u'datetime',
            },
            u'timezone': {
                u'xpath': u'//m:Items/t:CalendarItem/t:TimeZone',
            },
            u'date_time_created': {
                u'xpath': u'//m:Items/t:CalendarItem/t:DateTimeCreated',
                u'cast': u'datetime',
            },
            u'cancelled': {
                u'xpath': u'//m:Items/t:CalendarItem/t:IsCancelled',
                u'cast': u'bool',
            },
            u'sensitivity':
            {
                u'xpath': u'//m:Items/t:CalendarItem/t:Sensitivity',
            },
            u'html_body': {
                u'xpath': u'//m:Items/t:CalendarItem/t:Body[@BodyType="HTML"]',
            },
            u'text_body': {
                u'xpath': u'//m:Items/t:CalendarItem/t:Body[@BodyType="Text"]',
            },
            u'_type': {
                u'xpath': u'//m:Items/t:CalendarItem/t:CalendarItemType',
            },
            u'reminder_minutes_before_start': {
                u'xpath': u'//m:Items/t:CalendarItem/t:ReminderMinutesBeforeStart',
                u'cast': u'int',
            },
            u'reminder_is_set': {
                u'xpath': u'//m:Items/t:CalendarItem/t:ReminderIsSet',
                u'cast': u'bool',
            },
            u'last_modified_at': {
                u'xpath': u'//m:Items/t:CalendarItem/t:LastModifiedTime',
                u'cast': u'datetime',
            },
            u'is_all_day': {
                u'xpath': u'//m:Items/t:CalendarItem/t:IsAllDayEvent',
                u'cast': u'bool',
            },
            u'conversation_id': {
                u'xpath': u'//m:Items/t:CalendarItem/t:ConversationId/@Id',
            },
            u'recurrence_id': {
                u'xpath': u'//m:Items/t:CalendarItem/t:RecurrenceId',
            },
            u'recurrence_end_date': {
                u'xpath': u'//m:Items/t:CalendarItem/t:Recurrence/t:EndDateRecurrence/t:EndDate',
                u'cast': u'date_only_naive',
            },
            u'recurrence_interval': {
                u'xpath': u'//m:Items/t:CalendarItem/t:Recurrence/*/t:Interval',
                u'cast': u'int',
            },
            u'recurrence_days': {
                u'xpath': u'//m:Items/t:CalendarItem/t:Recurrence/t:WeeklyRecurrence/t:DaysOfWeek',
            }
        }

        result = self.service._xpath_to_dict(element=response, property_map=property_map, namespace_map=soap_request.NAMESPACES)

        try:
            recurrence_node = response.xpath(u'//m:Items/t:CalendarItem/t:Recurrence', namespaces=soap_request.NAMESPACES)[0]
        except IndexError:
            recurrence_node = None

        if recurrence_node is not None:

            if recurrence_node.find('t:DailyRecurrence', namespaces=soap_request.NAMESPACES) is not None:
                result['recurrence'] = 'daily'

            elif recurrence_node.find('t:WeeklyRecurrence', namespaces=soap_request.NAMESPACES) is not None:
                result['recurrence'] = 'weekly'

            elif recurrence_node.find('t:AbsoluteMonthlyRecurrence', namespaces=soap_request.NAMESPACES) is not None:
                result['recurrence'] = 'monthly'

            elif recurrence_node.find('t:AbsoluteYearlyRecurrence', namespaces=soap_request.NAMESPACES) is not None:
                result['recurrence'] = 'yearly'

        extended_property_nodes = response.xpath(u'//m:Items/t:CalendarItem/t:ExtendedProperty',
                                                 namespaces=soap_request.NAMESPACES)

        for extended_property in extended_property_nodes:
            uri = extended_property.find('t:ExtendedFieldURI', namespaces=soap_request.NAMESPACES)
            if uri is not None:
                if not result.get('extended_properties'):
                    result['extended_properties'] = []

                result['extended_properties'].append(ExchangeExtendedProperty(
                    distinguished_property_set_id=uri.get('DistinguishedPropertySetId'),
                    property_name=uri.get('PropertyName'), property_type=uri.get('PropertyType'),
                    value=extended_property.findtext('t:Value', namespaces=soap_request.NAMESPACES))
                )

        return result

    def _parse_event_organizer(self, response):

        organizer = response.xpath(u'//m:Items/t:CalendarItem/t:Organizer/t:Mailbox', namespaces=soap_request.NAMESPACES)

        property_map = {
            u'name': {
                u'xpath': u't:Name'
            },
            u'email': {
                u'xpath': u't:EmailAddress'
            },
        }

        if organizer:
            return self.service._xpath_to_dict(element=organizer[0], property_map=property_map, namespace_map=soap_request.NAMESPACES)
        else:
            return None

    def _parse_event_resources(self, response):
        property_map = {
            u'name': {
                u'xpath': u't:Mailbox/t:Name'
            },
            u'email': {
                u'xpath': u't:Mailbox/t:EmailAddress'
            },
            u'response': {
                u'xpath': u't:ResponseType'
            },
            u'last_response': {
                u'xpath': u't:LastResponseTime',
                u'cast': u'datetime'
            },
        }

        result = []

        resources = response.xpath(u'//m:Items/t:CalendarItem/t:Resources/t:Attendee', namespaces=soap_request.NAMESPACES)

        for attendee in resources:
            attendee_properties = self.service._xpath_to_dict(element=attendee, property_map=property_map, namespace_map=soap_request.NAMESPACES)
            attendee_properties[u'required'] = True

            if u'last_response' not in attendee_properties:
                attendee_properties[u'last_response'] = None

            if u'email' in attendee_properties:
                result.append(attendee_properties)

        return result

    def _parse_event_attendees(self, response):

        property_map = {
            u'name': {
                u'xpath': u't:Mailbox/t:Name'
            },
            u'email': {
                u'xpath': u't:Mailbox/t:EmailAddress'
            },
            u'response': {
                u'xpath': u't:ResponseType'
            },
            u'last_response': {
                u'xpath': u't:LastResponseTime',
                u'cast': u'datetime'
            },
        }

        result = []

        required_attendees = response.xpath(u'//m:Items/t:CalendarItem/t:RequiredAttendees/t:Attendee', namespaces=soap_request.NAMESPACES)
        for attendee in required_attendees:
            attendee_properties = self.service._xpath_to_dict(element=attendee, property_map=property_map, namespace_map=soap_request.NAMESPACES)
            attendee_properties[u'required'] = True

            if u'last_response' not in attendee_properties:
                attendee_properties[u'last_response'] = None

            if u'email' in attendee_properties:
                result.append(attendee_properties)

        optional_attendees = response.xpath(u'//m:Items/t:CalendarItem/t:OptionalAttendees/t:Attendee', namespaces=soap_request.NAMESPACES)

        for attendee in optional_attendees:
            attendee_properties = self.service._xpath_to_dict(element=attendee, property_map=property_map, namespace_map=soap_request.NAMESPACES)
            attendee_properties[u'required'] = False

            if u'last_response' not in attendee_properties:
                attendee_properties[u'last_response'] = None

            if u'email' in attendee_properties:
                result.append(attendee_properties)

        return result

    def _parse_event_conflicts(self, response):
        conflicting_ids = response.xpath(u'//m:Items/t:CalendarItem/t:ConflictingMeetings/t:CalendarItem/t:ItemId', namespaces=soap_request.NAMESPACES)
        return [id_element.get(u"Id") for id_element in conflicting_ids]


class Exchange2010FolderService(BaseExchangeFolderService):

    def folder(self, id=None, **kwargs):
        return Exchange2010Folder(service=self.service, id=id, **kwargs)

    def get_folder(self, id):
        """
          :param str id:  The Exchange ID of the folder to retrieve from the Exchange store.

          Retrieves the folder specified by the id, from the Exchange store.

          **Examples**::

            folder = service.folder().get_folder(id)

        """

        return Exchange2010Folder(service=self.service, id=id)

    def new_folder(self, **properties):
        """
          new_folder(display_name=display_name, folder_type=folder_type, parent_id=parent_id)
          :param str display_name:  The display name given to the new folder.
          :param str folder_type:  The type of folder to create.  Possible values are 'Folder',
            'CalendarFolder', 'ContactsFolder', 'SearchFolder', 'TasksFolder'.
          :param str parent_id:  The parent folder where the new folder will be created.

          Creates a new folder with the given properties.  Not saved until you call the create() method.

          **Examples**::

            folder = service.folder().new_folder(
              display_name=u"New Folder Name",
              folder_type="CalendarFolder",
              parent_id='calendar',
            )
            folder.create()

        """

        return Exchange2010Folder(service=self.service, **properties)

    def find_folder(self, parent_id, traversal='Shallow'):
        """
          find_folder(parent_id)
          :param str parent_id:  The parent folder to list.

          This method will return a generator of sub-folders to a given
          parent folder.

          **Examples**::

            # Iterate through folders within the default 'calendar' folder.
            folders = service.folder().find_folder(parent_id='calendar')
            for folder in folders:
              print(folder.display_name)

            # Delete all folders within the 'calendar' folder.
            folders = service.folder().find_folder(parent_id='calendar')
            for folder in folders:
              folder.delete()
        """
        offset = 0
        last_batch = False

        while not last_batch:
            body = soap_request.find_folder(
                parent_id=parent_id, format=u'AllProperties',
                traversal=traversal, limit=self.service.batch_size,
                offset=offset,
            )
            xml_result = self.service.send(body)
            last_batch = "true" == xml_result.xpath(
                '//m:RootFolder/@IncludesLastItemInRange',
                namespaces=soap_request.NAMESPACES,
            )[0]
            offset = int(xml_result.xpath(
                '//m:RootFolder/@IndexedPagingOffset',
                namespaces=soap_request.NAMESPACES,
            )[0])
            batch = self._parse_response_for_find_folder(xml_result)
            for f in batch:
                yield f

    def _parse_response_for_find_folder(self, response):

        result = []
        folders = response.xpath(u'//t:Folders/t:*', namespaces=soap_request.NAMESPACES)
        for folder in folders:
            result.append(
                Exchange2010Folder(
                    service=self.service,
                    xml=etree.fromstring(etree.tostring(folder))  # Might be a better way to do this
                )
            )

        return result


class Exchange2010Folder(BaseExchangeFolder):
    def _init_from_service(self, id):
        body = soap_request.get_folder(folder_id=id, format=u'AllProperties')
        response_xml = self.service.send(body)
        properties = self._parse_response_for_get_folder(response_xml)
        self._update_properties(properties)
        return self

    def _init_from_xml(self, xml):
        properties = self._parse_response_for_get_folder(xml)
        self._update_properties(properties)

        return self

    def create(self):
        """
        Creates a folder in Exchange. ::

          calendar = service.folder().new_folder(
            display_name=u"New Folder Name",
            folder_type="CalendarFolder",
            parent_id='calendar',
          )
          calendar.create()
        """

        self.validate()
        body = soap_request.new_folder(self)

        response_xml = self.service.send(body)
        self._id, self._change_key = self._parse_id_and_change_key_from_response(response_xml)

        return self

    def delete(self):
        """
        Deletes a folder from the Exchange store. ::

          folder = service.folder().get_folder(id)
          print("Deleting folder: %s" % folder.display_name)
          folder.delete()
        """

        if not self.id:
            raise TypeError(u"You can't delete a folder that hasn't been created yet.")

        body = soap_request.delete_folder(self)

        response_xml = self.service.send(body)  # noqa
        # TODO: verify deletion
        self._id = None
        self._change_key = None

        return None

    def move_to(self, folder_id):
        """
        :param str folder_id: The Folder ID of what will be the new parent folder, of this folder.
        Move folder to a different location, specified by folder_id::

          folder = service.folder().get_folder(id)
          folder.move_to(folder_id="ID of new location's folder")
        """

        if not folder_id:
            raise TypeError(u"You can't move to a non-existant folder")

        if not isinstance(folder_id, BASESTRING_TYPES):
            raise TypeError(u"folder_id must be a string")

        if not self.id:
            raise TypeError(u"You can't move a folder that hasn't been created yet.")

        response_xml = self.service.send(soap_request.move_folder(self, folder_id))  # noqa

        result_id, result_key = self._parse_id_and_change_key_from_response(response_xml)
        if self.id != result_id:
            raise ValueError(u"MoveFolder returned success but requested folder not moved")

        self.parent_id = folder_id
        return self

    def _parse_response_for_get_folder(self, response):
        folder_xpath = '|'.join('descendant-or-self::t:%s' % t
                                for t in self.FOLDER_TYPES)
        path = response.xpath(folder_xpath, namespaces=soap_request.NAMESPACES)[0]
        result = self._parse_folder_properties(path)
        return result

    def _parse_folder_properties(self, response):

        property_map = {
            'folder_class': {
                'xpath': 't:FolderClass',
            },
            'display_name': {
                'xpath': 't:DisplayName',
            },
            'total_count': {
                'xpath': 't:TotalCount',
                'cast': 'int',
            },
            'child_folder_count': {
                'xpath': 't:ChildFolderCount',
                'cast': 'int',
            },
            'unread_count': {
                'xpath': 't:UnreadCount',
                'cast': 'int',
            },
        }

        self._id, self._change_key = self._parse_id_and_change_key_from_response(response)
        self._parent_id = self._parse_parent_id_and_change_key_from_response(response)[0]
        self.folder_type = etree.QName(response).localname

        result = self.service._xpath_to_dict(
            element=response, property_map=property_map,
            namespace_map=soap_request.NAMESPACES
        )

        effective_rights = {
            'delete': {
                'xpath': 't:Delete',
                'cast': 'bool',
            },
            'modify': {
                'xpath': 't:Modify',
                'cast': 'bool',
            },
            'read': {
                'xpath': 't:Read',
                'cast': 'bool',
            },
            'create_contents': {
                'xpath': 't:CreateContents',
                'cast': 'bool',
            },
            'create_hierarchy': {
                'xpath': 't:CreateHierarchy',
                'cast': 'bool',
            },
            'create_associated': {
                'xpath': 't:CreateAssociated',
                'cast': 'bool',
            }
        }

        effective_rights_element = response.xpath('t:EffectiveRights', namespaces=soap_request.NAMESPACES)[0]

        result.update({
            'effective_rights': self.service._xpath_to_dict(
                element=effective_rights_element, property_map=effective_rights,
                namespace_map=soap_request.NAMESPACES
            )
        })

        return result

    def _parse_id_and_change_key_from_response(self, response):

        id_elements = response.xpath('t:FolderId',
                                     namespaces=soap_request.NAMESPACES)

        if id_elements:
            id_element = id_elements[0]
            return id_element.get(u"Id", None), id_element.get(u"ChangeKey", None)
        else:
            return None, None

    def _parse_parent_id_and_change_key_from_response(self, response):

        id_elements = response.xpath('t:ParentFolderId',
                                     namespaces=soap_request.NAMESPACES)

        if id_elements:
            id_element = id_elements[0]
            return id_element.get(u"Id", None), id_element.get(u"ChangeKey", None)
        else:
            return None, None


class Exchange2010RoomService(BaseExchangeRoomService):
    def get_room_lists(self):
        return Exchange2010RoomLists(service=self.service)


class Exchange2010RoomLists(object):
    def __init__(self, service, xml_result=None):
        self.service = service
        self.count = None
        self._items = None

        if xml_result is not None:
            self._items = self._parse_response_for_all_room_lists(xml_result)
            self.count = len(self._items)

    @property
    def items(self):
        if self._items is not None:
            for item in self._items:
                yield item
            return

        body = soap_request.get_room_lists()
        xml_result = self.service.send(body)

        batch = self._parse_response_for_all_room_lists(xml_result)
        for t in batch:
            yield t

    def _parse_response_for_all_room_lists(self, xml):
        room_lists = xml.xpath(u'//m:RoomLists/t:Address',
                               namespaces=soap_request.NAMESPACES)
        if not room_lists:
            log.debug(u'No rooms returned.')
            return []

        items = []
        for room_list_xml in room_lists:
            log.debug(u'Adding room item to room list...')
            room_list = Exchange2010RoomListItem(service=self.service,
                                                 xml=room_list_xml)
            log.debug(u'Added room list with name %s and email address %s.',
                      room_list.name, room_list.email_address)
            items.append(room_list)

        return items

    def __repr__(self):
        if self._items is None:
            return "<Exchange2010RoomList: lazy>"

        return "<Exchange2010RoomList: [{}]>".format(
            ', '.join(repr(item) for item in self.items),
        )


class Exchange2010RoomListItem(object):
    name = None
    email_address = None
    routing_type = None
    mailbox_type = None

    def __init__(self, service, xml=None, **kwargs):
        self.service = service
        self._items = None

        if xml is not None:
            self._init_from_xml(xml)

    def _init_from_xml(self, xml):
        properties = self._parse_room_properties(xml)

        self._update_properties(properties)

        return self

    def _update_properties(self, properties):
        for key in properties:
            setattr(self, key, properties[key])

    def _parse_room_properties(self, response):
        # Use relative selectors here so that we can call this in the
        # context of each Contact element without deepcopying.
        property_map = {
            u'name': {
                u'xpath': u't:Name',
            },
            u'email_address': {
                u'xpath': u't:EmailAddress',
            },
            u'routing_type': {
                u'xpath': u't:RoutingType',
            },
            u'mailbox_type': {
                u'xpath': u't:MailboxType',
            }
        }

        return self.service._xpath_to_dict(
            element=response, property_map=property_map,
            namespace_map=soap_request.NAMESPACES,
        )

    @property
    def items(self):
        if self._items is not None:
            for item in self._items:
                yield item
            return

        body = soap_request.get_rooms(self.email_address)
        xml_result = self.service.send(body)

        batch = self._parse_response_for_all_rooms(xml_result)
        for t in batch:
            yield t

    def _parse_response_for_all_rooms(self, xml):
        rooms = xml.xpath(u'//m:Rooms/t:Room/t:Id', namespaces=soap_request.NAMESPACES)
        if not rooms:
            log.debug(u'No rooms returned.')
            return []

        items = []
        for room_xml in rooms:
            log.debug(u'Adding room item to room list...')
            room = Exchange2010RoomItem(service=self.service, xml=room_xml)
            log.debug(u'Added room with name %s and email address %s.', room.name, room.email_address)
            items.append(room)

        return items

    def __repr__(self):
        return "<Exchange2010RoomListItem: {}>".format(self.name.encode('utf-8'))


class Exchange2010RoomItem(object):
    name = None
    email_address = None
    routing_type = None
    mailbox_type = None

    def __init__(self, service, xml=None, **kwargs):
        self.service = service

        if xml is not None:
            self._init_from_xml(xml)

    def _init_from_xml(self, xml):
        properties = self._parse_room_properties(xml)

        self._update_properties(properties)

        return self

    def _update_properties(self, properties):
        for key in properties:
            setattr(self, key, properties[key])

    def _parse_room_properties(self, response):
        property_map = {
            u'name': {
                u'xpath': u't:Name',
            },
            u'email_address': {
                u'xpath': u't:EmailAddress',
            },
            u'routing_type': {
                u'xpath': u't:RoutingType',
            },
            u'mailbox_type': {
                u'xpath': u't:MailboxType',
            }
        }

        return self.service._xpath_to_dict(
            element=response, property_map=property_map,
            namespace_map=soap_request.NAMESPACES,
        )


class Exchange2010ContactService(BaseExchangeContactService):
    def get_contact(self, id):
        return Exchange2010ContactItem(service=self.service, id=id)

    def find_contacts(self, query=None, initial_name=None, final_name=None,
                      max_entries=100):
        """
        :param str query: AQS query string
        :param str initial_name: Lower bound on contact names (lexicographically)
        :param str final_name: Upper bound on contact names
        :param int max_entries: Maximum number of matches
        """
        body = soap_request.find_contact_items(
            self.folder_id, query_string=query, initial_name=initial_name,
            final_name=final_name, max_entries=max_entries,
        )
        response_xml = self.service.send(body)
        return Exchange2010ContactList(service=self.service,
                                       folder_id=self.folder_id,
                                       xml_result=response_xml)

    def get_all_contacts(self):
        """
        Return a list of all contacts in the current folder.
        """
        return Exchange2010ContactList(service=self.service,
                                       folder_id=self.folder_id)


class Exchange2010ContactList(object):
    """
    Creates & Stores a list of Exchange2010ContactItem objects in the
    "self.items" variable.
    """
    def __init__(self, service, folder_id=None, xml_result=None):
        self.service = service
        self.folder_id = folder_id
        self.count = None
        self._items = None

        if xml_result is not None:
            self._items = self._parse_response_for_all_contacts(xml_result)
            self.count = len(self._items)

    @property
    def items(self):
        """
        Iterable of contact items. If the list has been initialized with a
        pre-fetched XML response, this just iterates over self._items,
        otherwise it's a generator that fetches batches of contacts from
        Exchange on demand.
        """
        if self._items is not None:
            for item in self._items:
                yield item
            return

        offset = 0
        while True:
            body = soap_request.find_items(
                folder_id=self.folder_id, format=u'AllProperties',
                limit=self.service.batch_size, offset=offset,
            )
            xml_result = self.service.send(body)
            last_batch = "true" == xml_result.xpath(
                '//m:RootFolder/@IncludesLastItemInRange',
                namespaces=soap_request.NAMESPACES,
            )[0]
            self.count = int(xml_result.xpath(
                '//m:RootFolder/@TotalItemsInView',
                namespaces=soap_request.NAMESPACES,
            )[0])
            offset = int(xml_result.xpath(
                '//m:RootFolder/@IndexedPagingOffset',
                namespaces=soap_request.NAMESPACES,
            )[0])

            batch = self._parse_response_for_all_contacts(xml_result)

            for t in batch:
                yield t

            if last_batch:
                return

    def _parse_response_for_all_contacts(self, xml):
        contacts = xml.xpath(u'//t:Items/t:Contact',
                             namespaces=soap_request.NAMESPACES)
        if not contacts:
            log.debug(u'No contacts returned.')
            return []

        items = []
        for contact_xml in contacts:
            log.debug(u'Adding contact item to contact list...')
            contact = Exchange2010ContactItem(service=self.service,
                                              folder_id=self.folder_id,
                                              xml=contact_xml)
            log.debug(u'Added contact with id %s and display name %s.',
                      contact.id, contact.display_name)
            items.append(contact)

        return items

    def __repr__(self):
        if self._items is None:
            return "<Exchange2010ContactList: lazy for folder {!r}>".format(self.folder_id)
        return "<Exchange2010ContactList: [{}]>".format(
            ', '.join(repr(item) for item in self.items),
        )


class Exchange2010ContactItem(BaseExchangeContactItem):
    def _init_from_service(self, id):
        body = soap_request.get_item(exchange_id=id, format=u'AllProperties')
        response_xml = self.service.send(body)

        return self._init_from_xml(response_xml)

    def _init_from_xml(self, xml):
        properties = self._parse_contact_properties(xml)

        self._id = properties.pop('id')
        self._change_key = properties.pop('change_key')

        self._update_properties(properties)

        physical_addresses = []
        xml_phys_addresses = xml.xpath(u'//t:PhysicalAddresses', namespaces=soap_request.NAMESPACES)

        for xml_phys in xml_phys_addresses:
            addr_props = self._parse_physical_addresses(xml_phys)
            physical_addresses.append(addr_props)
        self.physical_addresses = physical_addresses

        return self

    def _parse_contact_properties(self, response):
        # Use relative selectors here so that we can call this in the
        # context of each Contact element without deepcopying.
        property_map = {
            u'id': {
                u'xpath': u'descendant-or-self::t:Contact/t:ItemId/@Id',
            },
            u'change_key': {
                u'xpath': u'descendant-or-self::t:Contact/t:ItemId/@ChangeKey',
            },
            u'folder_id': {
                u'xpath': u'descendant-or-self::t:Contact/t:ParentFolderId/@Id',
            },
            u'first_name': {
                u'xpath': u'descendant-or-self::t:Contact/t:CompleteName/t:FirstName',
            },
            u'last_name': {
                u'xpath': u'descendant-or-self::t:Contact/t:CompleteName/t:LastName',
            },
            u'full_name': {
                u'xpath': u'descendant-or-self::t:Contact/t:CompleteName/t:FullName',
            },
            u'display_name': {
                u'xpath': u'descendant-or-self::t:Contact/t:DisplayName',
            },
            u'sort_name': {
                u'xpath': u'descendant-or-self::t:Contact/t:FileAs',
            },
            u'email_address1': {
                u'xpath': u"descendant-or-self::t:Contact/t:EmailAddresses/t:Entry[@Key='EmailAddress1']",
            },
            u'email_address2': {
                u'xpath': u"descendant-or-self::t:Contact/t:EmailAddresses/t:Entry[@Key='EmailAddress2']",
            },
            u'email_address3': {
                u'xpath': u"descendant-or-self::t:Contact/t:EmailAddresses/t:Entry[@Key='EmailAddress3']",
            },
            u'birthday': {
                u'xpath': u'descendant-or-self::t:Contact/t:Birthday',
                u'cast': u'date_only_naive',
            },
            u'job_title': {
                u'xpath': u'descendant-or-self::t:Contact/t:JobTitle',
            },
            u'department': {
                u'xpath': u'descendant-or-self::t:Contact/t:Department',
            },
            u'company_name': {
                u'xpath': u'descendant-or-self::t:Contact/t:CompanyName',
            },
            u'office_location': {
                u'xpath': u'descendant-or-self::t:Contact/t:OfficeLocation',
            },
            u'primary_phone': {
                u'xpath': u"descendant-or-self::t:Contact/t:PhoneNumbers/t:Entry[@Key='PrimaryPhone']",
            },
            u'business_phone': {
                u'xpath': u"descendant-or-self::t:Contact/t:PhoneNumbers/t:Entry[@Key='BusinessPhone']",
            },
            u'home_phone': {
                u'xpath': u"descendant-or-self::t:Contact/t:PhoneNumbers/t:Entry[@Key='HomePhone']",
            },
            u'mobile_phone': {
                u'xpath': u"descendant-or-self::t:Contact/t:PhoneNumbers/t:Entry[@Key='MobilePhone']",
            },
        }
        return self.service._xpath_to_dict(
            element=response, property_map=property_map,
            namespace_map=soap_request.NAMESPACES,
        )

    def _parse_physical_addresses(self, xml):
        # Use relative selectors here so that we can call this in the
        # context of each Contact element without deepcopying.
        property_map = {
            u'street': {
                u'xpath': u'descendant-or-self::t:Street',
            },
            u'city': {
                u'xpath': u'descendant-or-self::t:City',
            },
            u'state': {
                u'xpath': u'descendant-or-self::t:State',
            },
            u'country_or_region': {
                u'xpath': u'descendant-or-self::t:CountryOrRegion',
            },
            u'postal_code': {
                u'xpath': u'descendant-or-self::t:PostalCode',
            },
        }
        return self.service._xpath_to_dict(
            element=xml, property_map=property_map,
            namespace_map=soap_request.NAMESPACES,
        )

    def __repr__(self):
        return "<Exchange2010ContactItem: {}>".format(self.display_name.encode('utf-8'))


BODY_TYPE_HTML = u'HTML'
BODY_TYPE_TEXT = u'Text'
BODY_TYPES = [BODY_TYPE_HTML, BODY_TYPE_TEXT]


class Exchange2010MailService(BaseExchangeMailService):
    def get_mail(self, id):
        return Exchange2010MailItem(service=self.service, id=id)

    def list_mails(self, idonly=False):
        return Exchange2010MailList(service=self.service, folder_id=self.folder_id, idonly=idonly)

    def get_attachment(self, attachment_id):
        """
        downloads and parses an Email Attachment. Returns Dictionary
        with this format:
        {u'content': '<b64encoded content>',
         u'name': 'Kermit_the_Frog.jpg',
         u'content_type': 'image/jpeg'}
        """
        property_map = {
            u'name': {
                u'xpath': u'descendant-or-self::t:Name',
            },
            u'content_type': {
                u'xpath': u'descendant-or-self::t:ContentType',
            },
            u'content': {
                u'xpath': u'descendant-or-self::t:Content',
            },
        }

        xml_request = soap_request.get_attachments([attachment_id])
        response = self.service.send(xml_request)
        atts = response.xpath(u'//t:FileAttachment',
                              namespaces=soap_request.NAMESPACES)
        att_dict = None
        for xml in atts:
            att_dict = self.service._xpath_to_dict(
                element=xml, property_map=property_map,
                namespace_map=soap_request.NAMESPACES,
            )

        return att_dict

    def send_mime(self, subject, mime, recipients, cc_recipients=[], bcc_recipients=[],
                  params={}, attachments=[]):
        """
          List of recipients (and CC and BCC) are expected to be a list of either strings or tuples ('name', 'email_address')
        """
        for list_of_recipients in (recipients, cc_recipients, bcc_recipients):
            for i, recipient in enumerate(list_of_recipients):
                if isinstance(recipient, six.string_types):
                    list_of_recipients[i] = email.utils.parseaddr(recipient)
                elif not isinstance(recipient, tuple):
                    raise ValueError('Invalid email format: %s' % recipient)
        log.info('Sending email to recipients: {main}, CC to {cc}, BCC to {bcc}'.format(main=recipients,
                                                                                        cc=cc_recipients, bcc=bcc_recipients))
        folder = "drafts"
        disposition = "SaveOnly"
        response = self.service.send(soap_request.create_mime_email(subject, mime, recipients, cc_recipients,
                                                                    bcc_recipients, params=params, folder=folder,
                                                                    disposition=disposition))
        atts = response.xpath(u'//t:Message',
                              namespaces=soap_request.NAMESPACES)

        att_dict = None
        property_map = {
            u'id': {
                u'xpath': u'descendant-or-self::t:ItemId/@Id',
            },
            u'change_key': {
                u'xpath': u'descendant-or-self::t:ItemId/@ChangeKey',
            }
        }
        for xml in atts:
            att_dict = self.service._xpath_to_dict(
                element=xml, property_map=property_map,
                namespace_map=soap_request.NAMESPACES,
            )
            break

        if att_dict:
            if attachments:
                response = self.service.send(soap_request.create_attachment(att_dict['id'], att_dict['change_key'],
                                                                            attachments))
                atts = response.xpath(u'//t:FileAttachment',
                                      namespaces=soap_request.NAMESPACES)

                attach_dict = None
                property_map = {
                    u'id': {
                        u'xpath': u'descendant-or-self::t:AttachmentId/@Id',
                    },
                    u'root_id': {
                        u'xpath': u'descendant-or-self::t:AttachmentId/@RootItemId',
                    },
                    u'change_key': {
                        u'xpath': u'descendant-or-self::t:AttachmentId/@RootItemChangeKey',
                    }
                }
                for xml in atts:
                    attach_dict = self.service._xpath_to_dict(
                        element=xml, property_map=property_map,
                        namespace_map=soap_request.NAMESPACES,
                    )
                    break

                if attach_dict:
                    self.service.send(soap_request.update_email(attach_dict['root_id'], attach_dict['change_key'],
                                                                subject))
            else:
                self.service.send(soap_request.update_email(att_dict['id'], att_dict['change_key'],
                                                            subject))

        return att_dict

    def send(self, subject, body, recipients, cc_recipients=[], bcc_recipients=[], body_type=BODY_TYPE_HTML,
             params={}, attachments=[]):
        """
          List of recipients (and CC and BCC) are expected to be a list of either strings or tuples ('name', 'email_address')
        """
        for list_of_recipients in (recipients, cc_recipients, bcc_recipients):
            for i, recipient in enumerate(list_of_recipients):
                if isinstance(recipient, six.string_types):
                    list_of_recipients[i] = email.utils.parseaddr(recipient)
                elif not isinstance(recipient, tuple):
                    raise ValueError('Invalid email format: %s' % recipient)
        log.info('Sending email to recipients: {main}, CC to {cc}, BCC to {bcc}'.format(main=recipients, cc=cc_recipients, bcc=bcc_recipients))
        folder = "drafts"
        disposition = "SaveOnly"
        response = self.service.send(soap_request.create_email(subject, body, recipients, cc_recipients,
                                                               bcc_recipients, body_type, params=params, folder=folder,
                                                               disposition=disposition))
        atts = response.xpath(u'//t:Message',
                              namespaces=soap_request.NAMESPACES)
        att_dict = None
        property_map = {
            u'id': {
                u'xpath': u'descendant-or-self::t:ItemId/@Id',
            },
            u'change_key': {
                u'xpath': u'descendant-or-self::t:ItemId/@ChangeKey',
            }
        }
        for xml in atts:
            att_dict = self.service._xpath_to_dict(
                element=xml, property_map=property_map,
                namespace_map=soap_request.NAMESPACES,
            )
            break

        if att_dict:
            if attachments:
                response = self.service.send(soap_request.create_attachment(att_dict['id'], att_dict['change_key'],
                                                                            attachments))
                atts = response.xpath(u'//t:FileAttachment',
                                      namespaces=soap_request.NAMESPACES)

                attach_dict = None
                property_map = {
                    u'id': {
                        u'xpath': u'descendant-or-self::t:AttachmentId/@Id',
                    },
                    u'root_id': {
                        u'xpath': u'descendant-or-self::t:AttachmentId/@RootItemId',
                    },
                    u'change_key': {
                        u'xpath': u'descendant-or-self::t:AttachmentId/@RootItemChangeKey',
                    }
                }
                for xml in atts:
                    attach_dict = self.service._xpath_to_dict(
                        element=xml, property_map=property_map,
                        namespace_map=soap_request.NAMESPACES,
                    )
                    break

                if attach_dict:
                    self.service.send(soap_request.update_email(attach_dict['root_id'], attach_dict['change_key'],
                                                                subject))
            else:
                self.service.send(soap_request.update_email(att_dict['id'], att_dict['change_key'],
                                                            subject))
        return att_dict


class Exchange2010MailList(object):
    def __init__(self, service=None, folder_id=u'inbox', xml_result=None, idonly=False):
        self.service = service
        self.folder_id = folder_id
        self.idonly = idonly
        self._items = None
        self.count = None

        if xml_result is not None:
            self._items = self._parse_response_for_all_mails(xml_result)
            self.load_extended_properties(self._items)
            self.count = len(self._items)

    @property
    def items(self):
        """
        Iterable of email messages. If the list has been initialized with
        a pre-fetched XML response, this just iterates over self._items,
        otherwise it's a generator that fetches batches of messages from
        Exchange on demand.
        """
        if self._items is not None:
            for item in self._item:
                yield item
            return

        offset = 0
        while True:
            body = soap_request.find_items(
                folder_id=self.folder_id, limit=self.service.batch_size,
                offset=offset, format=u'IdOnly' if self.idonly else u'AllProperties'
            )
            xml_result = self.service.send(body)
            last_batch = "true" == xml_result.xpath(
                '//m:RootFolder/@IncludesLastItemInRange',
                namespaces=soap_request.NAMESPACES,
            )[0]
            self.count = int(xml_result.xpath(
                '//m:RootFolder/@TotalItemsInView',
                namespaces=soap_request.NAMESPACES,
            )[0])
            offset = int(xml_result.xpath(
                '//m:RootFolder/@IndexedPagingOffset',
                namespaces=soap_request.NAMESPACES,
            )[0])

            batch = self._parse_response_for_all_mails(xml_result)
            if not self.idonly:
                self.load_extended_properties(batch)

            for t in batch:
                yield t

            if last_batch:
                return

    def load_extended_properties(self, items):
        """
        loads additional mail info via soap
        if there are no items, nothing is done (empty items would cause soap error 500)
        """
        if items:
            body = soap_request.get_mail_items(items)
            logging.info(etree.tostring(body))
            xml_result = self.service.send(body)

            self._parse_response_for_extended_properties(items, xml_result)

    def _parse_response_for_extended_properties(self, items, xml):
        mails = xml.xpath(u'//t:Message',
                          namespaces=soap_request.NAMESPACES)
        mail_dict = {}
        for m in items:
            mail_dict[m._id] = m

        if not mails:
            log.debug(u'No mails extended properties returned.')
            return

        for mail_xml in mails:
            id = mail_xml.xpath(u'descendant-or-self::t:Message/t:ItemId/@Id',
                                namespaces=soap_request.NAMESPACES)
            mail = mail_dict[id[0]]
            mail._init_from_xml(mail_xml)

    def _parse_response_for_all_mails(self, xml):
        mails = xml.xpath(u'//t:Items/t:Message',
                          namespaces=soap_request.NAMESPACES)
        if not mails:
            log.debug(u'No mails returned.')
            return []

        items = []
        for mail_xml in mails:
            log.debug(u'Adding message to mailbox...')
            mail = Exchange2010MailItem(service=self.service,
                                        folder_id=self.folder_id,
                                        xml=mail_xml)
            log.debug(u'Added mail with id %s and subject %s.',
                      mail.id, mail.subject)
            items.append(mail)

        return items


class Exchange2010MailItem(BaseExchangeMailItem):
    def _init_from_service(self, id):
        body = soap_request.get_item(exchange_id=id, format=u'AllProperties')
        response_xml = self.service.send(body)

        return self._init_from_xml(response_xml)

    def _init_from_xml(self, xml):
        # Load basic single properties...
        properties = self._parse_mail_properties(xml)
        self._id = properties.pop('id')
        self._change_key = properties.pop('change_key')
        self._update_properties(properties)

        # Now parse the more involved properties containing lists of
        # things.
        attachments = []
        recipients_to = []
        recipients_cc = []
        recipients_bcc = []
        # These need to be ./ or descendant::, otherwise they'll select
        # all matching nodes in the entire XML document.
        xml_attachments = xml.xpath(u'.//t:FileAttachment',
                                    namespaces=soap_request.NAMESPACES)
        xml_to_recipients = xml.xpath(u'.//t:ToRecipients/t:Mailbox',
                                      namespaces=soap_request.NAMESPACES)
        xml_cc_recipients = xml.xpath(u'.//t:CcRecipients/t:Mailbox',
                                      namespaces=soap_request.NAMESPACES)
        xml_bcc_recipients = xml.xpath(u'.//t:BccRecipients/t:Mailbox',
                                       namespaces=soap_request.NAMESPACES)

        for to_r in xml_to_recipients:
            to_r_props = self._parse_recipient(to_r)
            recipients_to.append(to_r_props)
        self.recipients_to = recipients_to

        for cc_r in xml_cc_recipients:
            cc_r_props = self._parse_recipient(cc_r)
            recipients_cc.append(cc_r_props)
        self.recipients_cc = recipients_cc

        for bcc_r in xml_bcc_recipients:
            bcc_r_props = self._parse_recipient(bcc_r)
            recipients_bcc.append(bcc_r_props)
        self.recipients_bcc = recipients_bcc

        for attachment in xml_attachments:
            att_props = self._parse_attachment(attachment)
            attachments.append(att_props)
        self.attachments = attachments

        return self

    def init_from_aco(self, obj, attachment_url=None):
        self._id = obj['eid']
        for meta in obj['detail']['meta']:
            if meta['label'] == 'Subject':
                self.subject = meta['value']
            elif meta['label'] == 'Sent':
                self.datetime_sent = meta['value']
            elif meta['label'] == 'Culture':
                self.culture = meta['value']
            elif meta['label'] == 'Size':
                self.size = meta['value']
            elif meta['label'] == 'Importance':
                self.importance = meta['value']
        self.load_extended_properties()
        if attachment_url is not None:
            import urllib
            import base64
            for att in self.attachments:
                att['att_url'] = attachment_url + "?" + urllib.urlencode(
                    (('att_id', base64.b64encode(att['id'])),)
                )

    def load_extended_properties(self, include_mime_content=False):
        body = soap_request.get_mail_items([self], include_mime_content=include_mime_content)
        xml_result = self.service.send(body)
        self._init_from_xml(xml_result)

    def _parse_mail_properties(self, xml):
        # Use relative selectors here so that we can call this in the
        # context of each Contact element without deepcopying.
        print(etree.tostring(xml))

        property_map = {
            u'id': {
                u'xpath': u'descendant-or-self::t:Message/t:ItemId/@Id',
            },
            u'change_key': {
                u'xpath': u'descendant-or-self::t:Message/t:ItemId/@ChangeKey',
            },
            u'subject': {
                u'xpath': u'descendant-or-self::t:Subject',
            },
            u'sender_email': {
                u'xpath': u'descendant-or-self::t:Message/t:Sender/t:Mailbox/t:EmailAddress',
            },
            u'sender_name': {
                u'xpath': u'descendant-or-self::t:Message/t:Sender/t:Mailbox/t:Name',
            },
            u'from_email': {
                u'xpath': u'descendant-or-self::t:Message/t:From/t:Mailbox/t:EmailAddress',
            },
            u'from_name': {
                u'xpath': u'descendant-or-self::t:Message/t:From/t:Mailbox/t:Name',
            },
            u'culture': {
                u'xpath': u'descendant-or-self::t:Message/t:Culture',
            },
            u'internet_message_id': {
                u'xpath': u'descendant-or-self::t:Message/t:InternetMessageId',
            },
            u'references': {
                u'xpath': u'descendant-or-self::t:Message/t:References',
            },
            u'in_reply_to': {
                u'xpath': u'descendant-or-self::t:Message/t:InReplyTo',
            },
            u'has_attachments': {
                u'xpath': u'descendant-or-self::t:Message/t:HasAttachments',
                u'cast': 'bool',
            },
            u'size': {
                u'xpath': u'descendant-or-self::t:Message/t:Size',
                u'cast': 'int',
            },
            u'importance': {
                u'xpath': u'descendant-or-self::t:Message/t:Importance',
            },
            u'received': {
                u'xpath': u'descendant-or-self::t:Message/t:DateTimeReceived',
                u'cast': 'datetime',
            },
            u'datetime_sent': {
                u'xpath': u'descendant-or-self::t:Message/t:DateTimeSent',
                u'cast': 'datetime',
            },
            u'datetime_created': {
                u'xpath': u'descendant-or-self::t:Message/t:DateTimeCreated',
                u'cast': 'datetime',
            },
            u'mimecontent': {
                u'xpath': u'descendant-or-self::t:Message/t:MimeContent',
            },
            u'html_body': {
                u'xpath': u'descendant-or-self::t:Message/t:Body[@BodyType="HTML"]',
            },
            u'text_body': {
                u'xpath': u'descendant-or-self::t:Message/t:Body[@BodyType="Text"]',
            },
            u'is_read': {
                u'xpath': u'descendant-or-self::t:Message/t:IsRead',
                u'cast': 'bool',
            },
        }
        return self.service._xpath_to_dict(
            element=xml, property_map=property_map,
            namespace_map=soap_request.NAMESPACES,
        )

    def _parse_attachment(self, xml):
        """
        Called in the context of each attachment node.
        """
        property_map = {
            u'id': {
                u'xpath': u'descendant-or-self::t:AttachmentId/@Id',
            },
            u'name': {
                u'xpath': u'descendant-or-self::t:Name',
            },
            u'content_type': {
                u'xpath': u'descendant-or-self::t:ContentType',
            },
            u'content_id': {
                u'xpath': u'descendant-or-self::t:ContentId',
            },
        }
        return self.service._xpath_to_dict(
            element=xml, property_map=property_map,
            namespace_map=soap_request.NAMESPACES,
        )

    def _parse_recipient(self, xml):
        """
        Called in the context of each recipient node.
        """
        property_map = {
            u'name': {
                u'xpath': u'descendant-or-self::t:Name',
            },
            u'email': {
                u'xpath': u'descendant-or-self::t:EmailAddress',
            },
        }
        return self.service._xpath_to_dict(
            element=xml, property_map=property_map,
            namespace_map=soap_request.NAMESPACES,
        )

    def __repr__(self):
        return "<Exchange2010MailItem: {}>".format(self.id)


class Exchange2010TaskService(BaseExchangeTaskService):
    def get_task(self, id):
        return Exchange2010TaskItem(service=self.service, id=id)

    def get_all_tasks(self):
        """
        Return a list of all tasks in the current folder.
        """
        return Exchange2010TaskList(service=self.service,
                                    folder_id=self.folder_id)


class Exchange2010TaskList(object):
    """
    Creates an iterator over a list of Exchange2010TaskItem objects in
    "self.items".
    """
    def __init__(self, service, folder_id=None, xml_result=None):
        self.service = service
        self.folder_id = folder_id
        self.count = None
        self._items = None

        if xml_result is not None:
            self._items = self._parse_response_for_all_tasks(xml_result)
            self.load_extended_properties(self._items)
            self.count = len(self._items)

    @property
    def items(self):
        """
        Iterable of task items. If the list has been initialized with a
        pre-fetched XML response, this just iterates over self._items,
        otherwise it's a generator that fetches batches of tasks from
        Exchange on demand.
        """
        if self._items is not None:
            for item in self._item:
                yield item
            return

        offset = 0
        while True:
            body = soap_request.find_items(
                folder_id=self.folder_id, format=u'IdOnly',
                limit=self.service.batch_size, offset=offset,
            )
            xml_result = self.service.send(body)
            last_batch = "true" == xml_result.xpath(
                '//m:RootFolder/@IncludesLastItemInRange',
                namespaces=soap_request.NAMESPACES,
            )[0]
            self.count = int(xml_result.xpath(
                '//m:RootFolder/@TotalItemsInView',
                namespaces=soap_request.NAMESPACES,
            )[0])
            offset = int(xml_result.xpath(
                '//m:RootFolder/@IndexedPagingOffset',
                namespaces=soap_request.NAMESPACES,
            )[0])

            batch = self._parse_response_for_all_tasks(xml_result)
            self.load_extended_properties(batch)

            for t in batch:
                yield t

            if last_batch:
                return

    def load_extended_properties(self, items):
        """
        loads additional task info via soap
        if there are no items, nothing is done (empty items would cause soap error 500)
        """
        if items:
            body = soap_request.get_item([i.id for i in items],
                                         format=u'AllProperties')
            logging.info(etree.tostring(body))
            xml_result = self.service.send(body)

            self._parse_response_for_extended_properties(items, xml_result)

    def _parse_response_for_extended_properties(self, items, xml):
        tasks = xml.xpath(u'//t:Task',
                          namespaces=soap_request.NAMESPACES)
        tasks_dict = {}
        for t in items:
            tasks_dict[t._id] = t

        if not tasks:
            log.debug(u'No tasks extended properties returned.')
            return

        for task_xml in tasks:
            id = task_xml.xpath(u'descendant-or-self::t:Task/t:ItemId/@Id',
                                namespaces=soap_request.NAMESPACES)
            task = tasks_dict[id[0]]
            task._init_from_xml(task_xml)

    def _parse_response_for_all_tasks(self, xml):
        tasks = xml.xpath(u'//t:Items/t:Task',
                          namespaces=soap_request.NAMESPACES)
        if not tasks:
            log.debug(u'No tasks returned.')
            return []

        items = []
        for task_xml in tasks:
            log.debug(u'Adding task item to task list...')
            task = Exchange2010TaskItem(service=self.service,
                                        folder_id=self.folder_id,
                                        xml=task_xml)
            log.debug(u'Added task with id %s and subject %s.',
                      task.id, task.subject)
            items.append(task)

        return items

    def __repr__(self):
        if self._items is None:
            return "<Exchange2010TaskList: lazy for folder {!r}>".format(self.folder_id)
        return "<Exchange2010TaskList: [{}]>".format(
            ', '.join(repr(item) for item in self._items),
        )


class Exchange2010TaskItem(BaseExchangeTaskItem):
    def _init_from_service(self, id):
        body = soap_request.get_item(exchange_id=id, format=u'AllProperties')
        response_xml = self.service.send(body)

        return self._init_from_xml(response_xml)

    def _init_from_xml(self, xml):
        properties = self._parse_task_properties(xml)

        self._id = properties.pop('id')
        self._change_key = properties.pop('change_key')

        self._update_properties(properties)

        return self

    def _parse_task_properties(self, response):
        # Use relative selectors here so that we can call this in the
        # context of each Contact element without deepcopying.
        property_map = {
            u'id': {
                u'xpath': u'descendant-or-self::t:Task/t:ItemId/@Id',
            },
            u'change_key': {
                u'xpath': u'descendant-or-self::t:Task/t:ItemId/@ChangeKey',
            },
            u'folder_id': {
                u'xpath': u'descendant-or-self::t:Task/t:ParentFolderId/@Id',
            },
            u'subject': {
                u'xpath': u'descendant-or-self::t:Task/t:Subject',
            },
            u'text_body': {
                u'xpath': u'descendant-or-self::t:Task/t:Body[@BodyType=\'Text\']',
            },
            u'html_body': {
                u'xpath': u'descendant-or-self::t:Task/t:Body[@BodyType=\'HTML\']',
            },
            u'categories': {
                u'xpath': u'descendant-or-self::t:Task/t:Categories/t:String',
            },
            u'is_draft': {
                u'xpath': u'descendant-or-self::t:Task/t:IsDraft',
                u'cast': u'bool',
            },
            u'sent_at': {
                u'xpath': u'descendant-or-self::t:Task/t:DateTimeSent',
                u'cast': u'datetime',
            },
            u'created_at': {
                u'xpath': u'descendant-or-self::t:Task/t:DateTimeCreated',
                u'cast': u'datetime',
            },
            u'due_date': {
                u'xpath': u"descendant-or-self::t:Task/t:DueDate",
                u'cast': u'date',
            },
            # TODO: find a way to represent recurrence
            # https://msdn.microsoft.com/en-us/library/office/aa564273(v=exchg.150).aspx
            #u'recurrence': {
            #    u'xpath': u"descendant-or-self::t:Task/t:Recurrence",
            #},
            u'is_complete': {
                u'xpath': u'descendant-or-self::t:Task/t:IsComplete',
                u'cast': u'bool',
            },
            u'owner': {
                u'xpath': u'descendant-or-self::t:Task/t:Owner',
            },
            u'start_date': {
                u'xpath': u'descendant-or-self::t:Task/t:StartDate',
                u'cast': u'date',
            },
            u'complete_date': {
                u'xpath': u'descendant-or-self::t:Task/t:CompleteDate',
                u'cast': u'date',
            },
            u'status': {
                u'xpath': u"descendant-or-self::t:Task/t:Status",
            },
            u'status_description': {
                u'xpath': u"descendant-or-self::t:Task/t:StatusDescription",
            },
            u'percent_complete': {
                u'xpath': u'descendant-or-self::t:Task/t:PercentComplete',
                u'cast': u'int',
            },
            u'importance': {
                u'xpath': u"descendant-or-self::t:Task/t:Importance",
            },
            u'companies': {
                u'xpath': u"descendant-or-self::t:Task/t:Companies/t:String",
            },
            u'last_modified_by': {
                u'xpath': u"descendant-or-self::t:Task/t:LastModifiedName",
            },
            u'last_modified_at': {
                u'xpath': u"descendant-or-self::t:Task/t:LastModifiedTime",
                u'cast': u'datetime',
            },
        }
        return self.service._xpath_to_dict(
            element=response, property_map=property_map,
            namespace_map=soap_request.NAMESPACES,
        )

    def __repr__(self):
        return "<Exchange2010TaskItem: {}>".format(self.subject.encode('utf-8'))


class Exchange2010NotificationService(object):
    """
    Handles all things related to notifications, push or pull,
    subscriptions, etc.
    """
    def __init__(self, service):
        self.service = service

    def subscribe_push(self, folder_ids, event_types, url, status_freq=None, watermark=None):
        # notify_svc.subscribe_push("Calendar", event_types='all', url="http://url.com", status_freq=1440)
        body = soap_request.subscribe_push(folder_ids, event_types, url,
                                           status_freq)
        response = self.service.send(body)
        sub_id = response.xpath('//m:SubscriptionId',
                                namespaces=soap_request.NAMESPACES)[0]
        watermark = response.xpath('//m:Watermark',
                                   namespaces=soap_request.NAMESPACES)[0]
        return NotificationSubscription(sub_id.text, watermark.text)

    #TODO: implement UNSUBSCRIBE

    def parse_push_notification(self, body):
        """
        Process a raw push notification sent by Exchange.
        :param str body: Bytestring containing the XML request.

        Returns a dict containing a list of EWS item IDs for each event
        type.
        """
        xml_body = etree.XML(body)
        log.debug(etree.tostring(xml_body, pretty_print=True))
        events = dict()
        for event_type, xml_event_type in soap_request.NOTIFICATION_EVENT_TYPES.items():
            if event_type == 'moved':
                if xml_body.xpath('//t:MovedEvent', namespaces=soap_request.NAMESPACES):
                    events['moved'] = {
                        'item_id': xml_body.xpath('//t:MovedEvent/t:ItemId/@Id',
                                                  namespaces=soap_request.NAMESPACES),
                        'old_item_id': xml_body.xpath('//t:MovedEvent/t:OldItemId/@Id',
                                                      namespaces=soap_request.NAMESPACES),
                        'parent_folder': xml_body.xpath('//t:MovedEvent/t:ParentFolderId/@Id',
                                                        namespaces=soap_request.NAMESPACES),
                        'old_parent_folder': xml_body.xpath('//t:MovedEvent/t:OldParentFolderId/@Id',
                                                            namespaces=soap_request.NAMESPACES),
                        }
                else:
                    events['moved'] = []
            else:
                events[event_type] = xml_body.xpath(
                    '//t:{}/t:ItemId/@Id'.format(xml_event_type),
                    namespaces=soap_request.NAMESPACES,
                )
        return events
