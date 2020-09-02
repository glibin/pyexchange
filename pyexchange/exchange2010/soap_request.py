"""
(c) 2013 LinkedIn Corp. All rights reserved.
Licensed under the Apache License, Version 2.0 (the "License");?you may not use this file except in compliance with the License. You may obtain a copy of the License at  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software?distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
"""
from lxml.builder import ElementMaker
from ..utils import convert_datetime_to_utc
from ..compat import _unicode
import base64

MSG_NS = u'http://schemas.microsoft.com/exchange/services/2006/messages'
TYPE_NS = u'http://schemas.microsoft.com/exchange/services/2006/types'
SOAP_NS = u'http://schemas.xmlsoap.org/soap/envelope/'

NAMESPACES = {u'm': MSG_NS, u't': TYPE_NS, u's': SOAP_NS}

M = ElementMaker(namespace=MSG_NS, nsmap=NAMESPACES)
T = ElementMaker(namespace=TYPE_NS, nsmap=NAMESPACES)

EXCHANGE_DATETIME_FORMAT = u"%Y-%m-%dT%H:%M:%SZ"
EXCHANGE_DATE_FORMAT = u"%Y-%m-%d"

DISTINGUISHED_IDS = (
    'calendar', 'contacts', 'deleteditems', 'drafts', 'inbox', 'journal', 'notes', 'outbox', 'sentitems',
    'tasks', 'msgfolderroot', 'root', 'junkemail', 'searchfolders', 'voicemail', 'recoverableitemsroot',
    'recoverableitemsdeletions', 'recoverableitemsversions', 'recoverableitemspurges', 'archiveroot',
    'archivemsgfolderroot', 'archivedeleteditems', 'archiverecoverableitemsroot',
    'Archiverecoverableitemsdeletions', 'Archiverecoverableitemsversions', 'Archiverecoverableitemspurges',
)

NOTIFICATION_EVENT_TYPES = {
    'copied': 'CopiedEvent',
    'created': 'CreatedEvent',
    'deleted': 'DeletedEvent',
    'modified': 'ModifiedEvent',
    'moved': 'MovedEvent',
    'new_mail': 'NewMailEvent',
    # Apparently exchange does not recognize this event.
    #'free_busy_changed': 'FreeBusyChangedEvent',
}


def exchange_header():

    return T.RequestServerVersion({u'Version': u'Exchange2010'})


def folder_id_xml(folder_id):
    """
    Turn a single folder_id into the corresponding XML element, which is
    either DistinguishedFolderId, or FolderId.
    """
    if folder_id in DISTINGUISHED_IDS:
        return T.DistinguishedFolderId(Id=folder_id)
    else:
        return T.FolderId(Id=folder_id)


def resource_node(element, resources):
    """
    Helper function to generate a person/conference room node from an email address

    <t:OptionalAttendees>
      <t:Attendee>
          <t:Mailbox>
              <t:EmailAddress>{{ attendee_email }}</t:EmailAddress>
          </t:Mailbox>
      </t:Attendee>
    </t:OptionalAttendees>
    """

    for attendee in resources:
        element.append(
            T.Attendee(
                T.Mailbox(
                    T.EmailAddress(attendee.email)
                )
            )
        )

    return element


def delete_field(field_uri):
    """
        Helper function to request deletion of a field. This is necessary when you want to overwrite values instead of
        appending.

        <t:DeleteItemField>
          <t:FieldURI FieldURI="calendar:Resources"/>
        </t:DeleteItemField>
    """

    root = T.DeleteItemField(
        T.FieldURI(FieldURI=field_uri)
    )

    return root


def convert_id(id_value, destination_format, format=u'EwsId',
               mailbox=u'a@b.com'):
    return M.ConvertId(
        M.SourceIds(
            T.AlternateId(
                Format=format,
                Id=id_value,
                Mailbox=mailbox,
            )
        ),
        DestinationFormat=destination_format,
    )


def get_item(exchange_id, format=u"Default", additional_properties=None):
    """
      Requests a calendar item from the store.

      exchange_id is the id for this event in the Exchange store.

      format controls how much data you get back from Exchange. Full docs are here, but acceptible values
      are IdOnly, Default, and AllProperties.

      http://msdn.microsoft.com/en-us/library/aa564509(v=exchg.140).aspx

      <m:GetItem  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
              xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types">
        <m:ItemShape>
            <t:BaseShape>{format}</t:BaseShape>
        </m:ItemShape>
        <m:ItemIds>
            <t:ItemId Id="{exchange_id}"/>
        </m:ItemIds>
    </m:GetItem>

    """

    elements = list()
    if type(exchange_id) == list:
        for item in exchange_id:
            elements.append(T.ItemId(Id=item))
    else:
        elements = [T.ItemId(Id=exchange_id)]

    if additional_properties:
        additional_properties = list(map(
            lambda x: T.ExtendedFieldURI(
                DistinguishedPropertySetId=x.distinguished_property_set_id,
                PropertyName=x.property_name,
                PropertyType=x.property_type),
            additional_properties if isinstance(additional_properties, list) else [additional_properties]
        ))
    else:
        additional_properties = []

    shapes = [T.BaseShape(format)]

    if additional_properties:
        shapes.append(T.AdditionalProperties(*additional_properties))

    root = M.GetItem(
        M.ItemShape(
            *shapes
        ),
        M.ItemIds(
            *elements
        )
    )
    return root


def get_calendar_items(format=u"Default", calendar_id=u'calendar',
                       start=None, end=None, max_entries=1000,
                       delegate_for=None, additional_properties=None):
    start = start.strftime(EXCHANGE_DATETIME_FORMAT)
    end = end.strftime(EXCHANGE_DATETIME_FORMAT)

    if calendar_id == u'calendar':
        if delegate_for is None:
            target = M.ParentFolderIds(T.DistinguishedFolderId(Id=calendar_id))
        else:
            target = M.ParentFolderIds(
                T.DistinguishedFolderId(
                    {'Id': 'calendar'},
                    T.Mailbox(T.EmailAddress(delegate_for))
                )
            )
    else:
        target = M.ParentFolderIds(T.FolderId(Id=calendar_id))

    if additional_properties:
        additional_properties = list(map(
            lambda x: T.ExtendedFieldURI(
                DistinguishedPropertySetId=x.distinguished_property_set_id,
                PropertyName=x.property_name,
                PropertyType=x.property_type),
            additional_properties if isinstance(additional_properties, list) else [additional_properties]
        ))
    else:
        additional_properties = []

    shapes = [T.BaseShape(format)]

    if additional_properties:
        shapes.append(T.AdditionalProperties(*additional_properties))

    root = M.FindItem(
        {'Traversal': 'Shallow'},
        M.ItemShape(
            *shapes
        ),
        M.CalendarView({
            u'MaxEntriesReturned': _unicode(max_entries),
            u'StartDate': start,
            u'EndDate': end,
            }),
        target,
        )

    return root


def sync_calendar_items(calendar_id='calendar', format='Default', delegate_for=None, sync_state=None):
    if calendar_id == 'calendar':
        if delegate_for is None:
            target = M.SyncFolderId(T.DistinguishedFolderId(Id=calendar_id))
        else:
            target = M.SyncFolderId(
                T.DistinguishedFolderId(
                    {'Id': 'calendar'},
                    T.Mailbox(T.EmailAddress(delegate_for))
                )
            )
    else:
        target = M.SyncFolderId(T.FolderId(Id=calendar_id))

    items = [M.ItemShape(T.BaseShape(format)), target, M.MaxChangesReturned('512')]

    if sync_state:
        items.append(M.SyncState(sync_state))

    root = M.SyncFolderItems(
        *items
    )

    return root


def get_room_lists():
    return M.GetRoomLists()


def get_rooms(email):
    return M.GetRooms(M.RoomList(T.EmailAddress(email)))


def find_contact_items(folder_id, initial_name=None, final_name=None,
                       max_entries=100, **kwargs):
    root = find_items(folder_id, **kwargs)
    criteria = {'MaxEntriesReturned': str(max_entries)}
    if initial_name:
        criteria['InitialName'] = initial_name
    if final_name:
        criteria['FinalName'] = final_name
    root.find(
        'm:ItemShape', namespaces=NAMESPACES,
    ).addnext(M.ContactsView(**criteria))
    return root


def find_items(folder_id, query_string=None, format=u'Default',
               limit=None, offset=0):
    root = M.FindItem(
        M.ItemShape(T.BaseShape(format)),
        Traversal=u'Shallow',
    )
    if offset or (limit is not None):
        limit = limit or 1000  # the default in Exchange, apparently
        root.append(M.IndexedPageItemView(
            MaxEntriesReturned=str(limit),
            Offset=str(offset),
            BasePoint='Beginning',
        ))
    root.append(M.ParentFolderIds(folder_id_xml(folder_id)))
    if query_string:
        root.append(M.QueryString(query_string))

    return root


def get_attachments(ids):
    root = M.GetAttachment(
        M.AttachmentIds()
    )

    items_node = root.xpath("//m:AttachmentIds", namespaces=NAMESPACES)[0]
    for i in ids:
        items_node.append(T.AttachmentId(Id=i))
    return root


def get_mail_items(items, format=u'Default', include_mime_content=False):
    incl_mime_content = "true"
    if not include_mime_content:
        incl_mime_content = "false"

    root = M.GetItem(
        M.ItemShape(T.BaseShape(format),
                    T.IncludeMimeContent(incl_mime_content)),
        M.ItemIds()
    )

    items_node = root.xpath("//m:ItemIds", namespaces=NAMESPACES)[0]
    for i in items:
        if i._change_key:
            items_node.append(T.ItemId(Id=i._id, ChangeKey=i._change_key))
        else:
            items_node.append(T.ItemId(Id=i._id))
    return root


def get_master(exchange_id, format=u"Default"):
    """
      Requests a calendar item from the store.

      exchange_id is the id for this event in the Exchange store.

      format controls how much data you get back from Exchange. Full docs are here, but acceptible values
      are IdOnly, Default, and AllProperties.

      http://msdn.microsoft.com/en-us/library/aa564509(v=exchg.140).aspx

      <m:GetItem  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
              xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types">
        <m:ItemShape>
            <t:BaseShape>{format}</t:BaseShape>
        </m:ItemShape>
        <m:ItemIds>
            <t:RecurringMasterItemId OccurrenceId="{exchange_id}"/>
        </m:ItemIds>
    </m:GetItem>

    """

    root = M.GetItem(
        M.ItemShape(
            T.BaseShape(format)
        ),
        M.ItemIds(
            T.RecurringMasterItemId(OccurrenceId=exchange_id)
        )
    )
    return root


def get_occurrence(exchange_id, instance_index, format=u"Default"):
    """
      Requests one or more calendar items from the store matching the master & index.

      exchange_id is the id for the master event in the Exchange store.

      format controls how much data you get back from Exchange. Full docs are here, but acceptible values
      are IdOnly, Default, and AllProperties.

      GetItem Doc:
      http://msdn.microsoft.com/en-us/library/aa564509(v=exchg.140).aspx
      OccurrenceItemId Doc:
      http://msdn.microsoft.com/en-us/library/office/aa580744(v=exchg.150).aspx

      <m:GetItem  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
              xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types">
        <m:ItemShape>
            <t:BaseShape>{format}</t:BaseShape>
        </m:ItemShape>
        <m:ItemIds>
          {% for index in instance_index %}
            <t:OccurrenceItemId RecurringMasterId="{exchange_id}" InstanceIndex="{{ index }}"/>
          {% endfor %}
        </m:ItemIds>
      </m:GetItem>
    """

    root = M.GetItem(
        M.ItemShape(
            T.BaseShape(format)
        ),
        M.ItemIds()
    )

    items_node = root.xpath("//m:ItemIds", namespaces=NAMESPACES)[0]
    for index in instance_index:
        items_node.append(T.OccurrenceItemId(RecurringMasterId=exchange_id, InstanceIndex=str(index)))
    return root


def get_folder(folder_id, format=u"Default"):

    id = T.DistinguishedFolderId(Id=folder_id) if folder_id in DISTINGUISHED_IDS else T.FolderId(Id=folder_id)

    root = M.GetFolder(
        M.FolderShape(
            T.BaseShape(format)
        ),
        M.FolderIds(id)
    )
    return root


def new_folder(folder):

    id = T.DistinguishedFolderId(Id=folder.parent_id) if folder.parent_id in DISTINGUISHED_IDS else T.FolderId(Id=folder.parent_id)

    if folder.folder_type == u'Folder':
        folder_node = T.Folder(T.DisplayName(folder.display_name))
    elif folder.folder_type == u'CalendarFolder':
        folder_node = T.CalendarFolder(T.DisplayName(folder.display_name))

    root = M.CreateFolder(
        M.ParentFolderId(id),
        M.Folders(folder_node)
    )
    return root


def find_folder(parent_id, format=u"Default", traversal='Shallow',
                limit=None, offset=0):
    root = M.FindFolder(
        M.FolderShape(T.BaseShape(format)),
        Traversal=traversal,
    )
    if offset or (limit is not None):
        limit = limit or 1000  # the default in Exchange, apparently
        root.append(M.IndexedPageFolderView(
            MaxEntriesReturned=str(limit),
            Offset=str(offset),
            BasePoint='Beginning',
        ))
    root.append(M.ParentFolderIds(folder_id_xml(parent_id)))
    return root


def delete_folder(folder):

    root = M.DeleteFolder(
        {u'DeleteType': 'HardDelete'},
        M.FolderIds(
            T.FolderId(Id=folder.id)
        )
    )
    return root


def new_event(event):
    """
    Requests a new event be created in the store.

    http://msdn.microsoft.com/en-us/library/aa564690(v=exchg.140).aspx

    <m:CreateItem SendMeetingInvitations="SendToAllAndSaveCopy"
                xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages"
                xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types">
      <m:SavedItemFolderId>
          <t:DistinguishedFolderId Id="calendar"/>
      </m:SavedItemFolderId>
      <m:Items>
          <t:CalendarItem>
              <t:Subject>{event.subject}</t:Subject>
              <t:Body BodyType="HTML">{event.subject}</t:Body>
              <t:Start></t:Start>
              <t:End></t:End>
              <t:Sensitivity></t:Sensitivity>
              <t:Location></t:Location>
              <t:RequiredAttendees>
                  {% for attendee_email in meeting.required_attendees %}
                  <t:Attendee>
                      <t:Mailbox>
                          <t:EmailAddress>{{ attendee_email }}</t:EmailAddress>
                      </t:Mailbox>
                  </t:Attendee>
               HTTPretty   {% endfor %}
              </t:RequiredAttendees>
              {% if meeting.optional_attendees %}
              <t:OptionalAttendees>
                  {% for attendee_email in meeting.optional_attendees %}
                      <t:Attendee>
                          <t:Mailbox>
                              <t:EmailAddress>{{ attendee_email }}</t:EmailAddress>
                          </t:Mailbox>
                      </t:Attendee>
                  {% endfor %}
              </t:OptionalAttendees>
              {% endif %}
              {% if meeting.conference_room %}
              <t:Resources>
                  <t:Attendee>
                      <t:Mailbox>
                          <t:EmailAddress>{{ meeting.conference_room.email }}</t:EmailAddress>
                      </t:Mailbox>
                  </t:Attendee>
              </t:Resources>
              {% endif %}
              </t:CalendarItem>
      </m:Items>
  </m:CreateItem>
    """

    id = T.DistinguishedFolderId(Id=event.calendar_id) if event.calendar_id in DISTINGUISHED_IDS else T.FolderId(Id=event.calendar_id)

    start = convert_datetime_to_utc(event.start)
    end = convert_datetime_to_utc(event.end)

    root = M.CreateItem(
        M.SavedItemFolderId(id),
        M.Items(
            T.CalendarItem(
                T.Subject(event.subject),
                T.Body(event.text_body or u'', BodyType="Text"),
                )
        ),
        SendMeetingInvitations="SendToAllAndSaveCopy"
    )

    calendar_node = root.xpath(u'/m:CreateItem/m:Items/t:CalendarItem', namespaces=NAMESPACES)[0]

    if event.reminder_minutes_before_start:
        calendar_node.append(T.ReminderIsSet('true'))
        calendar_node.append(T.ReminderMinutesBeforeStart(str(event.reminder_minutes_before_start)))
    else:
        calendar_node.append(T.ReminderIsSet('false'))

    calendar_node.append(T.Start(start.strftime(EXCHANGE_DATETIME_FORMAT)))
    calendar_node.append(T.End(end.strftime(EXCHANGE_DATETIME_FORMAT)))

    if event.is_all_day:
        calendar_node.append(T.IsAllDayEvent('true'))

    if event.created:
        calendar_node.append(T.DateTimeCreated(convert_datetime_to_utc(event.created)))

    calendar_node.append(T.Location(event.location or u''))

    calendar_node.append(T.Sensitivity(event.sensitivity))

    if event.required_attendees:
        calendar_node.append(resource_node(element=T.RequiredAttendees(), resources=event.required_attendees))

    if event.optional_attendees:
        calendar_node.append(resource_node(element=T.OptionalAttendees(), resources=event.optional_attendees))

    if event.resources:
        calendar_node.append(resource_node(element=T.Resources(), resources=event.resources))

    if event.extended_properties:
        for extended_property in event.extended_properties:
            calendar_node.append(T.ExtendedProperty(
                T.ExtendedFieldURI(DistinguishedPropertySetId=extended_property.distinguished_property_set_id,
                                   PropertyName=extended_property.property_name,
                                   PropertyType=extended_property.property_type),
                T.Value(extended_property.value),
            ))

    if event.recurrence:

        if event.recurrence == u'daily':
            recurrence = T.DailyRecurrence(
                T.Interval(str(event.recurrence_interval)),
                )
        elif event.recurrence == u'weekly':
            recurrence = T.WeeklyRecurrence(
                T.Interval(str(event.recurrence_interval)),
                T.DaysOfWeek(event.recurrence_days),
                )
        elif event.recurrence == u'monthly':
            recurrence = T.AbsoluteMonthlyRecurrence(
                T.Interval(str(event.recurrence_interval)),
                T.DayOfMonth(str(event.start.day)),
                )
        elif event.recurrence == u'yearly':
            recurrence = T.AbsoluteYearlyRecurrence(
                T.DayOfMonth(str(event.start.day)),
                T.Month(event.start.strftime("%B")),
                )

        calendar_node.append(
            T.Recurrence(
                recurrence,
                T.EndDateRecurrence(
                    T.StartDate(event.start.strftime(EXCHANGE_DATE_FORMAT)),
                    T.EndDate(event.recurrence_end_date.strftime(EXCHANGE_DATE_FORMAT)),
                    )
            )
        )

    return root


def delete_event(event):
    """

    Requests an item be deleted from the store.


    <DeleteItem
        xmlns="http://schemas.microsoft.com/exchange/services/2006/messages"
        xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
        DeleteType="HardDelete"
        SendMeetingCancellations="SendToAllAndSaveCopy"
        AffectedTaskOccurrences="AllOccurrences">
            <ItemIds>
                <t:ItemId Id="{{ id }}" ChangeKey="{{ change_key }}"/>
            </ItemIds>
    </DeleteItem>

    """
    root = M.DeleteItem(
        M.ItemIds(
            T.ItemId(Id=event.id, ChangeKey=event.change_key)
        ),
        DeleteType="HardDelete",
        SendMeetingCancellations="SendToAllAndSaveCopy",
        AffectedTaskOccurrences="AllOccurrences"
    )

    return root


def move_event(event, folder_id):

    id = T.DistinguishedFolderId(Id=folder_id) if folder_id in DISTINGUISHED_IDS else T.FolderId(Id=folder_id)

    root = M.MoveItem(
        M.ToFolderId(id),
        M.ItemIds(
            T.ItemId(Id=event.id, ChangeKey=event.change_key)
        )
    )
    return root


def move_folder(folder, folder_id):

    id = T.DistinguishedFolderId(Id=folder_id) if folder_id in DISTINGUISHED_IDS else T.FolderId(Id=folder_id)

    root = M.MoveFolder(
        M.ToFolderId(id),
        M.FolderIds(
            T.FolderId(Id=folder.id)
        )
    )
    return root


def update_property_node(node_to_insert, field_uri):
    """ Helper function - generates a SetItemField which tells Exchange you want to overwrite the contents of a field."""
    root = T.SetItemField(
        T.FieldURI(FieldURI=field_uri),
        T.CalendarItem(node_to_insert)
    )
    return root


def update_item(event, updated_attributes, calendar_item_update_operation_type):
    """ Saves updates to an event in the store. Only request changes for attributes that have actually changed."""

    root = M.UpdateItem(
        M.ItemChanges(
            T.ItemChange(
                T.ItemId(Id=event.id, ChangeKey=event.change_key),
                T.Updates()
            )
        ),
        ConflictResolution=u"AlwaysOverwrite",
        MessageDisposition=u"SendAndSaveCopy",
        SendMeetingInvitationsOrCancellations=calendar_item_update_operation_type
    )

    update_node = root.xpath(u'/m:UpdateItem/m:ItemChanges/t:ItemChange/t:Updates', namespaces=NAMESPACES)[0]

    # if not send_only_to_changed_attendees:
    #   # We want to resend invites, which you do by setting an attribute to the same value it has. Right now, events
    #   # are always scheduled as Busy time, so we just set that again.
    #   update_node.append(
    #     update_property_node(field_uri="calendar:LegacyFreeBusyStatus", node_to_insert=T.LegacyFreeBusyStatus("Busy"))
    #   )

    if u'html_body' in updated_attributes:
        update_node.append(
            update_property_node(field_uri="item:Body", node_to_insert=T.Body(event.html_body, BodyType="HTML"))
        )

    if u'text_body' in updated_attributes:
        update_node.append(
            update_property_node(field_uri="item:Body", node_to_insert=T.Body(event.text_body, BodyType="Text"))
        )

    if u'subject' in updated_attributes:
        update_node.append(
            update_property_node(field_uri="item:Subject", node_to_insert=T.Subject(event.subject))
        )

    if u'start' in updated_attributes:
        start = convert_datetime_to_utc(event.start)

        update_node.append(
            update_property_node(field_uri="calendar:Start", node_to_insert=T.Start(start.strftime(EXCHANGE_DATETIME_FORMAT)))
        )

    if u'end' in updated_attributes:
        end = convert_datetime_to_utc(event.end)

        update_node.append(
            update_property_node(field_uri="calendar:End", node_to_insert=T.End(end.strftime(EXCHANGE_DATETIME_FORMAT)))
        )

    if u'location' in updated_attributes:
        update_node.append(
            update_property_node(field_uri="calendar:Location", node_to_insert=T.Location(event.location))
        )

    if u'attendees' in updated_attributes:

        if event.required_attendees:
            required = resource_node(element=T.RequiredAttendees(), resources=event.required_attendees)

            update_node.append(
                update_property_node(field_uri="calendar:RequiredAttendees", node_to_insert=required)
            )
        else:
            update_node.append(delete_field(field_uri="calendar:RequiredAttendees"))

        if event.optional_attendees:
            optional = resource_node(element=T.OptionalAttendees(), resources=event.optional_attendees)

            update_node.append(
                update_property_node(field_uri="calendar:OptionalAttendees", node_to_insert=optional)
            )
        else:
            update_node.append(delete_field(field_uri="calendar:OptionalAttendees"))

    if u'resources' in updated_attributes:
        if event.resources:
            resources = resource_node(element=T.Resources(), resources=event.resources)

            update_node.append(
                update_property_node(field_uri="calendar:Resources", node_to_insert=resources)
            )
        else:
            update_node.append(delete_field(field_uri="calendar:Resources"))

    if u'reminder_minutes_before_start' in updated_attributes:
        if event.reminder_minutes_before_start:
            update_node.append(
                update_property_node(field_uri="item:ReminderIsSet", node_to_insert=T.ReminderIsSet('true'))
            )
            update_node.append(
                update_property_node(
                    field_uri="item:ReminderMinutesBeforeStart",
                    node_to_insert=T.ReminderMinutesBeforeStart(str(event.reminder_minutes_before_start))
                )
            )
        else:
            update_node.append(
                update_property_node(field_uri="item:ReminderIsSet", node_to_insert=T.ReminderIsSet('false'))
            )

    if u'is_all_day' in updated_attributes:
        update_node.append(
            update_property_node(field_uri="calendar:IsAllDayEvent", node_to_insert=T.IsAllDayEvent(str(event.is_all_day).lower()))
        )

    if u'sensitivity' in updated_attributes:
        update_node.append(
            update_property_node(field_uri="item:Sensitivity", node_to_insert=T.Sensitivity(event.sensitivity)
        ))

    for attr in event.RECURRENCE_ATTRIBUTES:
        if attr in updated_attributes:

            recurrence_node = T.Recurrence()

            if event.recurrence == 'daily':
                recurrence_node.append(
                    T.DailyRecurrence(
                        T.Interval(str(event.recurrence_interval)),
                        )
                )
            elif event.recurrence == 'weekly':
                recurrence_node.append(
                    T.WeeklyRecurrence(
                        T.Interval(str(event.recurrence_interval)),
                        T.DaysOfWeek(event.recurrence_days),
                        )
                )
            elif event.recurrence == 'monthly':
                recurrence_node.append(
                    T.AbsoluteMonthlyRecurrence(
                        T.Interval(str(event.recurrence_interval)),
                        T.DayOfMonth(str(event.start.day)),
                        )
                )
            elif event.recurrence == 'yearly':
                recurrence_node.append(
                    T.AbsoluteYearlyRecurrence(
                        T.DayOfMonth(str(event.start.day)),
                        T.Month(event.start.strftime("%B")),
                        )
                )

            recurrence_node.append(
                T.EndDateRecurrence(
                    T.StartDate(event.start.strftime(EXCHANGE_DATE_FORMAT)),
                    T.EndDate(event.recurrence_end_date.strftime(EXCHANGE_DATE_FORMAT)),
                    )
            )

            update_node.append(
                update_property_node(field_uri="calendar:Recurrence", node_to_insert=recurrence_node)
            )

    return root


def subscribe_push(folder_ids, event_types, url, status_freq=None):
    folders = [folder_id_xml(folder) for folder in folder_ids]
    if event_types == 'all':
        event_types = NOTIFICATION_EVENT_TYPES.keys()
    events = [T.EventType(NOTIFICATION_EVENT_TYPES[e]) for e in event_types]
    if status_freq is None:
        status_freq = 30

    return M.Subscribe(
        M.PushSubscriptionRequest(
            T.FolderIds(*folders),
            T.EventTypes(*events),
            T.StatusFrequency(str(status_freq)),
            T.URL(str(url)),
        ),
    )


def unsubscribe_subscription_id(push_id):
    return M.Unsubscribe(
        M.SubscriptionId(push_id)
    )


def create_attachment(parent_id, change_key, attachments):
    """
    https://msdn.microsoft.com/en-us/library/aa565877(exchg.140).aspx
    <CreateAttachment xmlns="http://schemas.microsoft.com/exchange/services/2006/messages"
                    xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types">
    <ParentItemId Id="AAAtAE..." ChangeKey="CQAAABYA..."/>
    <Attachments>
      <t:FileAttachment>
        <t:Name>SomeFile</t:Name>
        <t:Content>AQIDBAU=</t:Content>
        <t:IsInline>false</t:IsInline>
        <t:ContentId>f_k1jtd87b1</t:ContentId>
      </t:FileAttachment>
    </Attachments>
    </CreateAttachment>
    """
    file_attachments = []
    for attachment in attachments:
        children_tags = [
            T.Name(attachment['name']),
            T.Content(base64.standard_b64encode(attachment['content'])),
        ]
        if 'is_inline' in attachment:
            is_inline = 'true' if attachment['is_inline'] else 'false'
            children_tags.append(T.IsInline(is_inline))
        if 'content_id' in attachment:
            content_id = str(attachment['content_id'])
            children_tags.append(T.ContentId(content_id))

        file_attachments.append(T.FileAttachment(*children_tags))

    return M.CreateAttachment(
        M.ParentItemId(Id=parent_id, ChangeKey=change_key),
        M.Attachments(*file_attachments)
    )


def update_email(email_id, change_key, subject, folder="sentitems",
                 disposition="SendAndSaveCopy"):
    """Update email (mostly for sending after attachments)"""
    return M.UpdateItem(
        M.SavedItemFolderId(
            T.DistinguishedFolderId(Id=folder)
        ),
        M.ItemChanges(
            T.ItemChange(
                T.ItemId(Id=email_id, ChangeKey=change_key),
                T.Updates(T.SetItemField(
                    T.FieldURI(FieldURI='item:Subject'),
                    T.Message(
                        T.Subject(subject)
                    )
                ))
            )
        ),
        MessageDisposition=disposition,
        ConflictResolution="AutoResolve"
    )


def create_email(subject, body, recipients, cc_recipients, bcc_recipients, body_type, params=None,
                 folder="sentitems", disposition="SendAndSaveCopy"):
    """
    https://msdn.microsoft.com/EN-US/library/office/aa566468(v=exchg.150).aspx
    <CreateItem MessageDisposition="SendAndSaveCopy" xmlns="http://schemas.microsoft.com/exchange/services/2006/messages">
      <SavedItemFolderId>
        <t:DistinguishedFolderId Id="drafts" />
      </SavedItemFolderId>
      <Items>
        <t:Message>
          <t:ItemClass>IPM.Note</t:ItemClass>
          <t:Subject>Project Action</t:Subject>
          <t:Body BodyType="Text">Priority - Update specification</t:Body>
          <t:ToRecipients>
            <t:Mailbox>
              <t:EmailAddress>sschmidt@example.com</t:EmailAddress>
            </t:Mailbox>
          </t:ToRecipients>
          <t:IsRead>false</t:IsRead>
        </t:Message>
      </Items>
    </CreateItem>
    Note on Mailbox:
    https://msdn.microsoft.com/en-us/library/office/aa565036(v=exchg.150).aspx
    <Mailbox>
       <Name/>
       <EmailAddress/>
       <RoutingType/>
       <MailboxType/>
       <ItemId/>
    </Mailbox>
    """
    # TODO probably should be using the already used resource_node method
    # Create email addresses first
    to_recipients = T.ToRecipients(*[T.Mailbox(
        T.Name(recipient[0]),
        T.EmailAddress(recipient[1])
    ) for recipient in recipients])
    cc_recipients = T.CcRecipients(*[T.Mailbox(
        T.Name(recipient[0]),
        T.EmailAddress(recipient[1])
    ) for recipient in cc_recipients])
    bcc_recipients = T.BccRecipients(*[T.Mailbox(
        T.Name(recipient[0]),
        T.EmailAddress(recipient[1])
    ) for recipient in bcc_recipients])

    message_params = []
    if params:
        for key, value in params.items():
            message_params.append(getattr(T, key)(value))

    return M.CreateItem(
        M.SavedItemFolderId(
            T.DistinguishedFolderId(Id=folder)
        ),
        M.Items(
            T.Message(
                T.ItemClass('IPM.Note'),
                T.Subject(subject),
                T.Body(body, BodyType=body_type),
                to_recipients,
                cc_recipients,
                bcc_recipients,
                T.IsRead('false'),
                *message_params
            )
        )

        , MessageDisposition=disposition)


def create_mime_email(subject, mime, recipients, cc_recipients, bcc_recipients, params=None,
                 folder="sentitems", disposition="SendAndSaveCopy"):
    """
    https://msdn.microsoft.com/EN-US/library/office/aa566468(v=exchg.150).aspx
    <CreateItem MessageDisposition="SendAndSaveCopy" xmlns="http://schemas.microsoft.com/exchange/services/2006/messages">
      <SavedItemFolderId>
        <t:DistinguishedFolderId Id="drafts" />
      </SavedItemFolderId>
      <Items>
        <t:Message>
          <t:ItemClass>IPM.Note</t:ItemClass>
          <t:Subject>Project Action</t:Subject>
          <t:MimeContent>base64 of email</t:Body>
          <t:ToRecipients>
            <t:Mailbox>
              <t:EmailAddress>sschmidt@example.com</t:EmailAddress>
            </t:Mailbox>
          </t:ToRecipients>
          <t:IsRead>false</t:IsRead>
        </t:Message>
      </Items>
    </CreateItem>
    Note on Mailbox:
    https://msdn.microsoft.com/en-us/library/office/aa565036(v=exchg.150).aspx
    <Mailbox>
       <Name/>
       <EmailAddress/>
       <RoutingType/>
       <MailboxType/>
       <ItemId/>
    </Mailbox>
    """
    # TODO probably should be using the already used resource_node method
    # Create email addresses first
    to_recipients = T.ToRecipients(*[T.Mailbox(
        T.Name(recipient[0]),
        T.EmailAddress(recipient[1])
    ) for recipient in recipients])
    cc_recipients = T.CcRecipients(*[T.Mailbox(
        T.Name(recipient[0]),
        T.EmailAddress(recipient[1])
    ) for recipient in cc_recipients])
    bcc_recipients = T.BccRecipients(*[T.Mailbox(
        T.Name(recipient[0]),
        T.EmailAddress(recipient[1])
    ) for recipient in bcc_recipients])

    message_params = []
    if params:
        for key, value in params.items():
            message_params.append(getattr(T, key)(value))

    return M.CreateItem(
        M.SavedItemFolderId(
            T.DistinguishedFolderId(Id=folder)
        ),
        M.Items(
            T.Message(
                T.ItemClass('IPM.Note'),
                T.Subject(subject),
                T.MimeContent(mime),
                to_recipients,
                cc_recipients,
                bcc_recipients,
                T.IsRead('false'),
                *message_params
            )
        )

        , MessageDisposition=disposition)


def get_user_availability(attendees, start, end):
    start = convert_datetime_to_utc(start)
    end = convert_datetime_to_utc(end)

    array = M.MailboxDataArray(*list(map(lambda x: T.MailboxData(T.Email(T.Address(x['email'])), T.AttendeeType('Optional')), attendees)))

    return M.GetUserAvailabilityRequest(
        T.TimeZone(T.Bias('0'),
                   T.StandardTime(T.Bias('0'), T.Time('00:00:00'), T.DayOrder('0'), T.Month('0'), T.DayOfWeek('Sunday')),
                   T.DaylightTime(T.Bias('0'), T.Time('00:00:00'), T.DayOrder('0'), T.Month('0'), T.DayOfWeek('Sunday'))
                   ),
        array,
        T.FreeBusyViewOptions(T.TimeWindow(
            T.StartTime(start.strftime(EXCHANGE_DATETIME_FORMAT)),
            T.EndTime(end.strftime(EXCHANGE_DATETIME_FORMAT))
        ), T.RequestedView('FreeBusy'))
    )
