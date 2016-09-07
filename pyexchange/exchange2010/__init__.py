"""
(c) 2013 LinkedIn Corp. All rights reserved.
Licensed under the Apache License, Version 2.0 (the "License");?you may not use this file except in compliance with the License. You may obtain a copy of the License at  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software?distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
"""

import logging
from ..base.calendar import BaseExchangeCalendarEvent, BaseExchangeCalendarService, ExchangeEventOrganizer, ExchangeEventResponse
from ..base.contacts import BaseExchangeContactService, BaseExchangeContactItem
from ..base.folder import BaseExchangeFolder, BaseExchangeFolderService
from ..base.mail import BaseExchangeMailService, BaseExchangeMailItem
from ..base.tasks import BaseExchangeTaskService, BaseExchangeTaskItem
from ..base.soap import ExchangeServiceSOAP, S
from ..exceptions import FailedExchangeException, ExchangeStaleChangeKeyException, ExchangeItemNotFoundException, ExchangeInternalServerTransientErrorException, ExchangeIrresolvableConflictException, InvalidEventType
from ..compat import BASESTRING_TYPES

from . import soap_request

from lxml import etree
from copy import deepcopy
from datetime import date
import warnings

log = logging.getLogger("pyexchange")


class Exchange2010Service(ExchangeServiceSOAP):

    def calendar(self, id="calendar"):
        return Exchange2010CalendarService(service=self, calendar_id=id)

    def contacts(self, folder_id="contacts"):
        return Exchange2010ContactService(service=self, folder_id=folder_id)

    def folder(self):
        return Exchange2010FolderService(service=self)

    def mail(self, folder_id="inbox"):
        return Exchange2010MailService(service=self, folder_id=folder_id)

    def tasks(self, folder_id="tasks"):
        return Exchange2010TaskService(service=self, folder_id=folder_id)

    def convert_id(self, from_id, destination_format, format='EwsId',
                   mailbox='a@b.com'):
        body = soap_request.convert_id(from_id, destination_format,
                                       format, mailbox)
        response = self.send(body)
        return response.xpath(u'//m:ConvertIdResponseMessage/m:AlternateId/@Id')

    def _send_soap_request(self, body, headers=None, retries=2, timeout=30, encoding="utf-8"):
        headers = {
            "Accept": "text/xml",
            "Content-type": "text/xml; charset=%s " % encoding
        }
        return super(Exchange2010Service, self)._send_soap_request(body, headers=headers, retries=retries, timeout=timeout, encoding=encoding)

    def _wrap_soap_xml_request(self, exchange_xml):
        return S.Envelope(
            S.Header(
                soap_request.T.RequestServerVersion(
                    Version="Exchange2010",
                ),
            ),
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

    def event(self, id=None, **kwargs):
        return Exchange2010CalendarEvent(service=self.service, id=id, **kwargs)

    def get_event(self, id):
        return Exchange2010CalendarEvent(service=self.service, id=id)

    def new_event(self, **properties):
        return Exchange2010CalendarEvent(service=self.service, calendar_id=self.calendar_id, **properties)

    def list_events(self, start=None, end=None, details=False, delegate_for=None):
        return Exchange2010CalendarEventList(service=self.service, calendar_id=self.calendar_id, start=start, end=end, details=details, delegate_for=delegate_for)


class Exchange2010CalendarEventList(object):
    """
    Creates & Stores a list of Exchange2010CalendarEvent items in the "self.events" variable.
    """

    def __init__(self, service=None, calendar_id=u'calendar', start=None, end=None, details=False, delegate_for=None):
        self.service = service
        self.count = 0
        self.start = start
        self.end = end
        self.events = list()
        self.event_ids = list()
        self.details = details
        self.delegate_for = delegate_for

        # This request uses a Calendar-specific query between two dates.
        body = soap_request.get_calendar_items(format=u'AllProperties', calendar_id=calendar_id, start=self.start, end=self.end, delegate_for=self.delegate_for)
        response_xml = self.service.send(body)
        self._parse_response_for_all_events(response_xml)

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

    def _init_from_service(self, id):
        log.debug(u'Creating new Exchange2010CalendarEvent object from ID')
        body = soap_request.get_item(exchange_id=id, format=u'AllProperties')
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

        if self.type != 'Occurrence':
            raise InvalidEventType("get_master method can only be called on a 'Occurrence' event type")

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

        return result

    def _parse_event_properties(self, response):

        property_map = {
            u'subject': {
                u'xpath': u'//m:Items/t:CalendarItem/t:Subject',
                },
            u'location':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:Location',
                    },
            u'availability':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:LegacyFreeBusyStatus',
                    },
            u'start':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:Start',
                    u'cast': u'datetime',
                    },
            u'end':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:End',
                    u'cast': u'datetime',
                    },
            u'html_body':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:Body[@BodyType="HTML"]',
                    },
            u'text_body':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:Body[@BodyType="Text"]',
                    },
            u'_type':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:CalendarItemType',
                    },
            u'reminder_minutes_before_start':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:ReminderMinutesBeforeStart',
                    u'cast': u'int',
                    },
            u'is_all_day':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:IsAllDayEvent',
                    u'cast': u'bool',
                    },
            u'recurrence_end_date':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:Recurrence/t:EndDateRecurrence/t:EndDate',
                    u'cast': u'date_only_naive',
                    },
            u'recurrence_interval':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:Recurrence/*/t:Interval',
                    u'cast': u'int',
                    },
            u'recurrence_days':
                {
                    u'xpath': u'//m:Items/t:CalendarItem/t:Recurrence/t:WeeklyRecurrence/t:DaysOfWeek',
                    },
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

        return result

    def _parse_event_organizer(self, response):

        organizer = response.xpath(u'//m:Items/t:CalendarItem/t:Organizer/t:Mailbox', namespaces=soap_request.NAMESPACES)

        property_map = {
            u'name':
                {
                    u'xpath': u't:Name'
                },
            u'email':
                {
                    u'xpath': u't:EmailAddress'
                },
            }

        if organizer:
            return self.service._xpath_to_dict(element=organizer[0], property_map=property_map, namespace_map=soap_request.NAMESPACES)
        else:
            return None

    def _parse_event_resources(self, response):
        property_map = {
            u'name':
                {
                    u'xpath': u't:Mailbox/t:Name'
                },
            u'email':
                {
                    u'xpath': u't:Mailbox/t:EmailAddress'
                },
            u'response':
                {
                    u'xpath': u't:ResponseType'
                },
            u'last_response':
                {
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
            u'name':
                {
                    u'xpath': u't:Mailbox/t:Name'
                },
            u'email':
                {
                    u'xpath': u't:Mailbox/t:EmailAddress'
                },
            u'response':
                {
                    u'xpath': u't:ResponseType'
                },
            u'last_response':
                {
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

    def find_folder(self, parent_id):
        """
          find_folder(parent_id)
          :param str parent_id:  The parent folder to list.

          This method will return a list of sub-folders to a given parent folder.

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

        body = soap_request.find_folder(parent_id=parent_id, format=u'AllProperties')
        response_xml = self.service.send(body)
        return self._parse_response_for_find_folder(response_xml)

    def list_folders(self, folder_type=u'all'):
        return Exchange2010FolderList(service=self.service, folder_type=folder_type)

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
        FOLDER_PATH = u'//t:Folder | //t:CalendarFolder | //t:ContactsFolder | //t:SearchFolder | //t:TasksFolder'

        path = response.xpath(FOLDER_PATH, namespaces=soap_request.NAMESPACES)[0]
        result = self._parse_folder_properties(path)
        return result

    def _parse_folder_properties(self, response):

        property_map = {
            u'display_name': {u'xpath': u't:DisplayName'},
            }

        self._id, self._change_key = self._parse_id_and_change_key_from_response(response)
        self._parent_id = self._parse_parent_id_and_change_key_from_response(response)[0]
        self.folder_type = etree.QName(response).localname

        return self.service._xpath_to_dict(element=response, property_map=property_map, namespace_map=soap_request.NAMESPACES)

    def _parse_id_and_change_key_from_response(self, response):

        id_elements = response.xpath(u'//t:FolderId', namespaces=soap_request.NAMESPACES)

        if id_elements:
            id_element = id_elements[0]
            return id_element.get(u"Id", None), id_element.get(u"ChangeKey", None)
        else:
            return None, None

    def _parse_parent_id_and_change_key_from_response(self, response):

        id_elements = response.xpath(u'//t:ParentFolderId', namespaces=soap_request.NAMESPACES)

        if id_elements:
            id_element = id_elements[0]
            return id_element.get(u"Id", None), id_element.get(u"ChangeKey", None)
        else:
            return None, None


class Exchange2010FolderList(object):
    """
    Creates & Stores a list of Exchange2010CalendarEvent items in the "self.events" variable.
    """

    def __init__(self, service=None, folder_type=u'all'):
        """
        @param folder_type: the type of folders to load. allowed_folder_types: (u'contacts', u'calendar', u'tasks')
        """
        allowed_folder_types = (u'contacts', u'calendar', u'tasks', u'all', u'inbox')
        if folder_type not in allowed_folder_types:
            raise FailedExchangeException

        self.service = service
        self.count = 0
        self.folders = list()
        self.folder_ids = list()

        if folder_type != u'all':
                body = soap_request.get_folder_items(folder_type, format=u'AllProperties')
                response_xml = self.service.send(body)
                self._parse_response_for_all_folders(response_xml, folder_type)
        else:
            # import all folders except the 'all' type
            for ft in allowed_folder_types[:-1]:
                body = soap_request.get_folder_items(ft, format=u'AllProperties')
                response_xml = self.service.send(body)
                self._parse_response_for_all_folders(response_xml, ft)

        # Populate the event ID list, for convenience reasons.
        for folder in self.folders:
            self.folder_ids.append(folder._id)

    def _parse_response_for_all_folders(self, response, folder_type):
        """
        This function will retrieve *most* of the event data, excluding Organizer & Attendee details
        """
        folder_xml_name = u'Folder'
        if folder_type == u'calendar':
            folder_xml_name = u'CalendarFolder'

        if folder_type == u'tasks':
            folder_xml_name = u'TasksFolder'

        if folder_type == u'contacts':
            folder_xml_name = u'ContactsFolder'

        if folder_type == u'inbox':
            folder_xml_name = u'Folder'

        folders = response.xpath(u'//m:FindFolderResponse/m:ResponseMessages/m:FindFolderResponseMessage/m:RootFolder/t:Folders/t:%s' % folder_xml_name, namespaces=soap_request.NAMESPACES)
        if folders:
            self.count += len(folders)
            log.debug(u'Found %s calendar folders' % len(folders))
            for folder in folders:
                self._add_folder(xml=soap_request.M.Items(deepcopy(folder)))
        else:
            log.debug(u'No %s folders found with search parameters.' % folder_type)

    def _add_folder(self, xml=None):
        log.debug(u'Adding new folder to all folder list.')
        folder = Exchange2010Folder(service=self.service, xml=xml)
        log.debug(u'Name of new fodler is %s' % folder._display_name)
        self.folders.append(folder)


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
        self.count = 0
        self.items = []

        if xml_result is None:
            # Fetch all contacts for a folder.
            body = soap_request.find_items(folder_id=folder_id,
                                           format=u'AllProperties')
            xml_result = self.service.send(body)

        self._parse_response_for_all_contacts(xml_result)

    def _parse_response_for_all_contacts(self, xml):
        contacts = xml.xpath(u'//t:Items/t:Contact',
                             namespaces=soap_request.NAMESPACES)
        if not contacts:
            log.debug(u'No contacts returned.')
            return

        self.count = len(contacts)
        for contact_xml in contacts:
            log.debug(u'Adding contact item to contact list...')
            contact = Exchange2010ContactItem(service=self.service,
                                              folder_id=self.folder_id,
                                              xml=contact_xml)
            log.debug(u'Added contact with id %s and display name %s.',
                      contact.id, contact.display_name)
            self.items.append(contact)

    def __repr__(self):
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
            },
            u'job_title': {
                u'xpath': u'descendant-or-self::t:Contact/t:JobTitle',
            },
            u'department': {
                u'xpath': u'descendant-or-self::t:Contact/t:Department',
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

    def __repr__(self):
        return "<Exchange2010ContactItem: {}>".format(self.display_name.encode('utf-8'))


class Exchange2010MailService(BaseExchangeMailService):
    def list_mails(self):
        return Exchange2010MailList(service=self.service, folder_id=self.folder_id)

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


class Exchange2010MailList(object):
    def __init__(self, service=None, folder_id=u'inbox', xml_result=None):
        self.service = service
        self.mail_folder_id = folder_id
        self.items = []

        if xml_result is None:
            # Fetch all contacts for a folder.
            body = soap_request.find_items(folder_id=folder_id,
                                           format=u'AllProperties')
            xml_result = self.service.send(body)

        self._parse_response_for_all_mails(xml_result)

    def load_extended_properties(self):
        """
        loads additional mail info via soap
        if there are no items, nothing is done (empty items would cause soap error 500)
        """
        if self.items:
            body = soap_request.get_mail_items(self.items)
            logging.info(etree.tostring(body))
            xml_result = self.service.send(body)

            self._parse_response_for_extended_properties(xml_result)

    def _parse_response_for_extended_properties(self, xml):
        mails = xml.xpath(u'//t:Message',
                          namespaces=soap_request.NAMESPACES)
        mail_dict = {}
        for m in self.items:
            mail_dict[m._id] = m

        if not mails:
            log.debug(u'No mails extended properties returned.')
            return

        for mail_xml in mails:
            id = mail_xml.xpath(u'descendant-or-self::t:Message/t:ItemId/@Id',
                                namespaces=soap_request.NAMESPACES)
            mail = mail_dict[id[0]]
            mail.load_details_from_xml(mail_xml)

    def _parse_response_for_all_mails(self, xml):
        mails = xml.xpath(u'//t:Items/t:Message',
                          namespaces=soap_request.NAMESPACES)
        if not mails:
            log.debug(u'No mails returned.')
            return

        self.count = len(mails)
        for mail_xml in mails:
            log.debug(u'Adding contact item to contact list...')
            mail = Exchange2010MailItem(service=self.service,
                                        folder_id=self.mail_folder_id,
                                        xml=mail_xml)
            log.debug(u'Added mail with id %s and subject %s.',
                      mail.id, mail.subject)
            self.items.append(mail)


class Exchange2010MailItem(BaseExchangeMailItem):
    def _init_from_service(self, id):
        body = soap_request.get_item(exchange_id=id, format=u'AllProperties')
        response_xml = self.service.send(body)

        return self._init_from_xml(response_xml)

    def _init_from_xml(self, xml):
        properties = self._parse_mail_properties(xml)

        self._id = properties.pop('id')
        self._change_key = properties.pop('change_key')

        self._update_properties(properties)

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

    def load_extended_properties(self):
        body = soap_request.get_mail_items([self])
        xml_result = self.service.send(body)
        mails = xml_result.xpath(u'//t:Message',
                                 namespaces=soap_request.NAMESPACES)
        for m in mails:
            # this should only happen once
            self.load_details_from_xml(m)

    def _parse_mail_properties(self, xml):
        # Use relative selectors here so that we can call this in the
        # context of each Contact element without deepcopying.

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
            u'sender_mail': {
                u'xpath': u'descendant-or-self::t:Message/t:Sender/t:Mailbox/t:EmailAddress',
            },
            u'sender_name': {
                u'xpath': u'descendant-or-self::t:Message/t:Sender/t:Mailbox/t:Name',
            },
            u'from_mail': {
                u'xpath': u'descendant-or-self::t:Message/t:From/t:Mailbox/t:EmailAddress',
            },
            u'from_name': {
                u'xpath': u'descendant-or-self::t:Message/t:From/t:Mailbox/t:Name',
            },
            u'culture': {
                u'xpath': u'descendant-or-self::t:Message/t:Culture',
            },
            u'has_attachments': {
                u'xpath': u'descendant-or-self::t:Message/t:HasAttachments',
            },
            u'size': {
                u'xpath': u'descendant-or-self::t:Message/t:Size',
            },
            u'importance': {
                u'xpath': u'descendant-or-self::t:Message/t:Importance',
            },
            u'received': {
                u'xpath': u'descendant-or-self::t:Message/t:DateTimeReceived',
            },
        }
        return self.service._xpath_to_dict(
            element=xml, property_map=property_map,
            namespace_map=soap_request.NAMESPACES,
        )

    def _parse_mail_extended_properties(self, xml):
        # Use relative selectors here so that we can call this in the
        # context of each Contact element without deepcopying.
        property_map = {
            u'datetime_sent': {
                u'xpath': u'descendant-or-self::t:Message/t:DateTimeSent',
            },
            u'datetime_created': {
                u'xpath': u'descendant-or-self::t:Message/t:DateTimeCreated',
            },
            u'mimecontent': {
                u'xpath': u'descendant-or-self::t:Message/t:MimeContent',
            },
            u'mail_body': {
                u'xpath': u'descendant-or-self::t:Message/t:Body',
            },
        }
        return self.service._xpath_to_dict(
            element=xml, property_map=property_map,
            namespace_map=soap_request.NAMESPACES,
        )

    def _parse_attachments(self, xml):
        # Use relative selectors here so that we can call this in the
        # context of each Contact element without deepcopying.
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
        # Use relative selectors here so that we can call this in the
        # context of each Contact element without deepcopying.
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

    def load_details_from_xml(self, xml, load_attachments=False):
        if load_attachments:
            raise NotImplemented
        properties = self._parse_mail_extended_properties(xml)
        self._update_properties(properties)

        # working get attachment call! :)
        # item = self.service.send(soap_request.get_attachments(['AAAdAENocmlzdG9waEBydWthaS51YmVyZ3JhcGUuY29tAEYAAAAAANaGNy8FozRNlNXwalrBrAIHAP/GjqevaOpAoUvDe14z/MUAAAti/4cAAP/GjqevaOpAoUvDe14z/MUAAAtjBWMAAAESABAAmk2jbTOnHE6mgVKBvZv3eQ==']))
        attachments = []
        recipients_to = []
        recipients_cc = []
        xml_attachments = xml.xpath(u'//t:FileAttachment', namespaces=soap_request.NAMESPACES)
        xml_to_recipients = xml.xpath(u'//t:ToRecipients/t:Mailbox', namespaces=soap_request.NAMESPACES)
        xml_cc_recipients = xml.xpath(u'//t:CcRecipients/t:Mailbox', namespaces=soap_request.NAMESPACES)
        for to_r in xml_to_recipients:
            to_r_props = self._parse_recipient(to_r)
            recipients_to.append(to_r_props)
        self.recipients_to = recipients_to

        for cc_r in xml_cc_recipients:
            cc_r_props = self._parse_recipient(cc_r)
            recipients_cc.append(cc_r_props)
        self.recipients_cc = recipients_cc

        for attachment in xml_attachments:
            att_props = self._parse_attachments(attachment)
            attachments.append(att_props)
        self.attachments = attachments
        return self

    def __repr__(self):
        return "<Exchange2010MailItem: {}>".format(self.subject.encode('utf-8'))


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
    Creates & Stores a list of Exchange2010ContactItem objects in the
    "self.items" variable.
    """
    def __init__(self, service, folder_id=None, xml_result=None):
        self.service = service
        self.folder_id = folder_id
        self.count = 0
        self.items = []

        if xml_result is None:
            # Fetch all contacts for a folder.
            body = soap_request.find_items(folder_id=folder_id,
                                           format=u'AllProperties')
            xml_result = self.service.send(body)

        self._parse_response_for_all_tasks(xml_result)

    def _parse_response_for_all_tasks(self, xml):
        tasks = xml.xpath(u'//t:Items/t:Task',
                          namespaces=soap_request.NAMESPACES)
        if not tasks:
            log.debug(u'No tasks returned.')
            return

        self.count = len(tasks)
        for task_xml in tasks:
            log.debug(u'Adding task item to task list...')
            task = Exchange2010TaskItem(service=self.service,
                                        folder_id=self.folder_id,
                                        xml=task_xml)
            log.debug(u'Added task with id %s and subject %s.',
                      task.id, task.subject)
            self.items.append(task)

    def __repr__(self):
        return "<Exchange2010TaskList: [{}]>".format(
            ', '.join(repr(item) for item in self.items),
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
            u'body': {
                u'xpath': u'descendant-or-self::t:Task/t:Body[@BodyType=\'Text\']',
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
                u'cast': u'datetime',
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
                u'cast': u'datetime',
            },
            u'status': {
                u'xpath': u"descendant-or-self::t:Task/t:Status",
            },
            u'status_description': {
                u'xpath': u"descendant-or-self::t:Task/t:StatusDescription",
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
