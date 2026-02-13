# The MIT License (MIT)
#
# Copyright (c) 2014-2024 Fraunhofer FKIE, Alexander Tiderko
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
##################################################################################

import json

import fnmatch
import os
import re

import logging

'''
If ROS is installed tries to find the path to given ROS package.
If it fails an empty string will be returned.
'''


def get_pkg_path(package_name):
    _get_pkg_path_var = None
    # try detect ROS package path
    # ROS2
    try:
        from ament_index_python.packages import get_package_share_directory
        package_dir = get_package_share_directory(package_name)
        return package_dir
    except Exception:
        pass
    # ROS1
    try:
        try:
            import rospkg
            rp = rospkg.RosPack()
            _get_pkg_path_var = rp.get_path
        except ImportError:
            try:
                import roslib
                _get_pkg_path_var = roslib.packages.get_pkg_dir
            except ImportError:
                pass
        if _get_pkg_path_var is not None:
            return _get_pkg_path_var(package_name)
    except Exception:
        pass
    return ''


class JsonGenerator:

    def __init__(self, input_path=None, output_path=None, typescript_path="", exclude=[], verbose=False):
        if verbose:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)
        if output_path is None:
            output_path = os.path.join(os.getcwd(), 'schemes')
            logging.info("Write schemes to default path: %s" % (output_path))
        else:
            logging.info("Write schemes to: %s" % (output_path))
        if not os.path.exists(output_path):
            os.mkdir(output_path)
        self.output_path = output_path
        self.output_path_ts = typescript_path

        if input_path is None:
            input_path = get_pkg_path("fkie_iop_builder")
            input_path = os.path.join(input_path, "jsidl")
            logging.info(
                "Read from default jsidl input path: %s" % (input_path))
        else:
            input_path = os.path.abspath(input_path)
            logging.info("Read jsidl files from: %s" % (input_path))

        # create a set with all xml files found in input_path
        self.xml_files = set()
        self.doc_files = {}
        for root, _dirnames, filenames in os.walk(input_path):
            subdirs = root.replace(input_path, '').split(os.path.sep)
            if not (set(subdirs) & set(exclude)):
                for filename in fnmatch.filter(filenames, '*.xml'):
                    xmlFile = os.path.join(root, filename)
                    self.xml_files.add(os.path.join(root, xmlFile))
            else:
                logging.debug("Skip folder: %s" % root)
        # known user defined formats used in variable_format_field e.g. ReportRangeSensorCompressedData
        self._known_formats = {}
        # counter variables for debug output
        current_idx = 0
        self._message_count = 0
        self._message_failed = []
        self._message_ids = dict()
        self._message_doubles = []
        self._message_double_ids = dict()
        self._service_uris = dict()
        # parse all files found in input_path
        for iXmlFile in sorted(self.xml_files):
            current_idx += 1
            logging.debug("Parse [%d/%d]: %s" %
                          (current_idx, len(self.xml_files), iXmlFile))
            self.parse_jsidl_file(iXmlFile)
        logging.info("%d message types found" % self._message_count)
        if self._message_failed:
            logging.warning("Parse errors in %d message types: \n\t%s" % (len(self._message_failed), '\n\t'.join(
                [f"{msgName}: {fname}, backtrace:\n{bTrace}" for msgName, fname, bTrace in self._message_failed])))
        if self._message_doubles:
            logging.warning("Skipped %d message types, their name was already been parsed. Rerun with debug (-v) for details!" % (
                len(self._message_doubles)))
        count_messages_with_same_id = 0
        for key, items in self._message_double_ids.items():
            if len(items) > 1:
                count_messages_with_same_id += 1
        if count_messages_with_same_id > 0:
            logging.warning(f"Added {count_messages_with_same_id} messages with same ID but different name:")
            for key, items in self._message_double_ids.items():
                if len(items) > 1:
                    logging.warning(f"  {key}:")
                    for item in items:
                        logging.warning(f"    - {item}:")
        logging.info("JSON schemes written to: %s" % (output_path))
        if self.output_path_ts:
            if not os.path.exists(self.output_path_ts):
                os.mkdir(self.output_path_ts)
            # write a list with all message names and their ids
            iop_message_ids_file = os.path.join(
                self.output_path_ts, f"IopMessageIds.ts")
            with open(iop_message_ids_file, 'w+') as tsf:
                tsf.write("export const IopMessageIds = {\n")
                for key, _msg_filename in self._message_ids.items():
                    tsf.write(f'  {key[1]}_{key[0]}: "{key[0]}" as const,\n')
                tsf.write("}\n")
            logging.info("All message names/ids written to: %s" % (iop_message_ids_file))
            # write a list with all service names and their uris
            iop_service_uri_file = os.path.join(
                self.output_path_ts, f"IopServiceUris.ts")
            with open(iop_service_uri_file, 'w+') as tsf:
                tsf.write("export const IopServiceUris = {\n")
                for key, item in self._service_uris.items():
                    tsf.write(f'  {key}: "{item}" as const,\n')
                tsf.write("}\n")
            logging.info("All service names/ids written to: %s" % (iop_service_uri_file))

    def parse_jsidl_file(self, filename):
        js = self._get_doc(filename)
        self.dirname = os.path.dirname(filename)
        logging.debug(f"current directory: {self.dirname}")
        found_message_def = False
        if js._element().name().localName() == "service_def":
            logging.debug(f"parse service: {js.name} [{js.id}]")
            js_key = js.name
            if js_key in self._service_uris:
                js_key = f"{js.name}{js.id.split(":")[-2].capitalize()}"
            self._service_uris[js_key] = js.id
        if hasattr(js, 'message_def'):
            found_message_def = True
            self._parse_jsidl_message_def(filename, js.message_def)
        if hasattr(js, 'message_set'):
            if hasattr(js.message_set, 'input_set'):
                if hasattr(js.message_set.input_set, 'message_def'):
                    found_message_def = True
                    self._parse_jsidl_message_def(
                        filename, js.message_set.input_set.message_def)
            if hasattr(js.message_set, 'output_set'):
                if hasattr(js.message_set.output_set, 'message_def'):
                    found_message_def = True
                    self._parse_jsidl_message_def(
                        filename, js.message_set.output_set.message_def)
        if not found_message_def:
            logging.debug(
                f"No 'message_def' or 'message_set' in {filename} found!")

        # parse message definitions
    def _parse_jsidl_message_def(self, filename, message_def):
        for counter in range(len(message_def)):
            try:
                logging.debug(
                    f"--- MESSAGE {counter + 1}/{len(message_def)}  ---  FILE {filename} ---")
                jsMsg = message_def[counter]
                self.msgIdHex = msgIdHex = jsMsg.message_id.hex()
                jsonStruct = {'title': jsMsg.name,
                              'messageId': msgIdHex,
                              'isCommand': True if jsMsg.is_command else False,
                              'description': ' '.join([a.value.strip() for a in jsMsg.description.orderedContent()]),
                              'type': 'object',
                              'properties': {},
                              'required': []
                              }

                if (msgIdHex, jsMsg.name) in self._message_ids:
                    self._message_doubles.append(
                        "%s(%s)" % (jsMsg.name, msgIdHex))
                    logging.debug(
                        f"skip message with already parsed message: {jsMsg.name}, ID: {msgIdHex}:\n  file       : {filename},\n  first found: {self._message_ids[(msgIdHex, jsMsg.name)]}")
                    continue

                if msgIdHex in self._message_double_ids:
                    self._message_double_ids[msgIdHex].append(jsMsg.name)
                else:
                    self._message_double_ids[msgIdHex] = [jsMsg.name]
                self._not_parsed = []
                self._current_msg_name = jsMsg.name
                self._message_ids[(msgIdHex, jsMsg.name)] = filename
                logging.debug(
                    f"Parse message: {jsMsg.name}, msg_id: {msgIdHex}")
                self._message_count += 1

                # Parse Header
                if jsMsg.header and jsMsg.header.orderedContent():
                    for hc in jsMsg.header.orderedContent():
                        self.parse_element(hc, jsonStruct, filename)
                elif jsMsg.declared_header:
                    js, incFile = self._resolve_type_ref(
                        jsMsg.declared_header.declared_type_ref, "header", filename)
                    for hc in js.value.orderedContent():
                        self.parse_element(hc, jsonStruct, incFile)
                # Parse Body
                if jsMsg.body and jsMsg.body.orderedContent():
                    for bc in jsMsg.body.orderedContent():
                        self.parse_element(bc, jsonStruct, filename)
                elif jsMsg.declared_body:
                    js, incFile = self._resolve_type_ref(
                        jsMsg.declared_body.declared_type_ref, "body", filename)
                    for bc in js.value.orderedContent():
                        self.parse_element(bc, jsonStruct, incFile)
                # Parse Footer
                if jsMsg.footer and jsMsg.footer.orderedContent():
                    for fc in jsMsg.footer.orderedContent():
                        self.parse_element(fc, jsonStruct, filename)
                elif jsMsg.declared_footer:
                    js, incFile = self._resolve_type_ref(
                        jsMsg.declared_footer.declared_type_ref, "footer", filename)
                    for fc in js.value.orderedContent():
                        self.parse_element(fc, jsonStruct, incFile)
                # write into the file only if no Exception occurs
                with open(os.path.join(self.output_path, f"{jsMsg.name}_{msgIdHex}.json"), 'w+') as schemeFile:
                    schemeFile.write(json.dumps(jsonStruct, indent=2))
            except Exception:
                import traceback
                # logging.warning(traceback.format_exc())
                self._message_failed.append(
                    (jsMsg.name, filename, traceback.format_exc()))

    def parse_tag_optional(self, element, force=False):
        # check for optional parameter and add an if-statement if it is true
        return force or hasattr(element.value, "optional") and str(
            element.value.optional) == "true"

    def get_json_type(self, fieldType):
        if 'integer' in fieldType:
            return 'number'
        if 'byte' in fieldType:
            return 'number'
        if 'string' == fieldType:
            return fieldType
        return 'UNKNOWN'

    def appendStruct(self, jsonStruct, name, jsonSubStruct):
        if 'properties' in jsonStruct:
            jsonStruct['properties'][name] = jsonSubStruct
        if 'items' in jsonStruct:
            jsonStruct['items']['anyOf'].append(jsonSubStruct)

    def create_simple_struct(self, jsonStruct, name, elType, optional, comment):
        jsonSubStruct = {'type': self.get_json_type(elType),
                         'jausType': elType,
                         'comment': comment,
                         }
        self.appendStruct(jsonStruct, name, jsonSubStruct)
        if not optional:
            jsonStruct['required'].append(name)
        return jsonSubStruct

    def create_complex_struct(self, jsonStruct, name, xType, optional, comment):
        jsonSubStruct = {'type': xType,
                         'comment': comment,
                         'required': []
                         }
        if xType == 'array':
            jsonSubStruct['items'] = {}
            jsonSubStruct['items']['anyOf'] = []
        else:
            jsonSubStruct['properties'] = {}
        self.appendStruct(jsonStruct, name, jsonSubStruct)
        if not optional:
            jsonStruct['required'].append(name)
        return jsonSubStruct

    def parse_element(self, element, jsonStruct, filename, depth=1):
        elName = element.elementDeclaration.name().localName()
        jsName = ''
        try:
            jsName = element.value.name
            self._known_formats[jsName] = (element, filename)
        except:
            pass
        logging.debug(f"parse <{elName} name: '{jsName}'>")

        if elName == "array":
            self.parse_array(element, jsonStruct, filename, depth)
        elif elName in ["record", "sequence"]:
            self.parse_record(element, jsonStruct, filename, depth)
        elif elName == "bit_field":
            self.parse_bit_field(element, jsonStruct, filename, depth)
        elif elName == "fixed_length_string":
            self.parse_fixed_length_string(
                element, jsonStruct, filename, depth)
        elif elName == "fixed_field":
            self.parse_fixed_field(element, jsonStruct, filename, depth)
        elif elName == "list":
            self.parse_list(element, jsonStruct, filename, depth)
        elif elName == "presence_vector":
            self.parse_presence_vector(element, jsonStruct, filename, depth)
        elif elName == "variable_field":
            self.parse_variable_field(element, jsonStruct, filename, depth)
        elif elName == "variable_format_field":
            self.parse_variable_format_field(
                element, jsonStruct, filename, depth)
        elif elName == "variable_length_field":
            self.parse_variable_length_field(
                element, jsonStruct, filename, depth)
        elif elName == "variable_length_string":
            self.parse_variable_length_string(
                element, jsonStruct, filename, depth)
        elif elName == "variant":
            self.parse_variant(element, jsonStruct, filename, depth)
        elif elName == "declared_array":
            self.parse_declared_array(element, jsonStruct, filename, depth)
        elif elName == "declared_bit_field":
            self.parse_declared_bit_field(
                element, jsonStruct, filename, depth)
        elif elName == "declared_fixed_field":
            self.parse_declared_fixed_field(
                element, jsonStruct, filename, depth)
        elif elName == "declared_list":
            self.parse_declared_list(element, jsonStruct, filename, depth)
        elif elName == "declared_record":
            self.parse_declared_record(element, jsonStruct, filename, depth)
        elif elName == "declared_variable_length_string":
            self.parse_declared_variable_length_string(
                element, jsonStruct, filename, depth)
        else:
            logging.info("skipped '%s' -- no parser implemented, message: %s, file: %s" %
                         (elName, self._current_msg_name, filename))
            self._not_parsed.append(elName)
            print(f"\nNOT PARSED: {elName}\n")
            raise

    def parse_array(self, element, jsonStruct, filename, depth=1, declared_name='', declared_comment='', declared_optional=False):
        name = self.get_name(element, force=declared_name)
        comment = self.get_comment(element, force=declared_comment)
        optional = self.parse_tag_optional(element, force=declared_optional)
        jsonSubStruct = self.create_complex_struct(
            jsonStruct, name, 'array', optional, comment)
        # add list elements
        for rc in element.value.orderedContent():
            if rc.elementDeclaration.name().localName() == "dimension":
                size = self._to_int(rc.value.size, filename)
                jsonSubStruct['minItems'] = size
                jsonSubStruct['maxItems'] = size
            else:
                self.parse_element(rc, jsonSubStruct, filename, depth + 1)

    def parse_record(self, element, jsonStruct, filename, depth=1, declared_name='', declared_comment='', declared_optional=False):
        name = self.get_name(element, force=declared_name)
        comment = self.get_comment(element, force=declared_comment)
        optional = self.parse_tag_optional(element, force=declared_optional)

        jsonSubStruct = self.create_complex_struct(
            jsonStruct, name, 'object', optional, comment)
        for rc in element.value.orderedContent():
            self.parse_element(rc, jsonSubStruct, filename, depth)

    def parse_variant(self, element, jsonStruct, filename, depth=1):
        name = self.get_name(element)
        comment = self.get_comment(element)
        optional = self.parse_tag_optional(element)
        jsonSubStruct = self.create_complex_struct(
            jsonStruct, name, 'array', optional, comment)
        # read count field first
        vTag_field = element.value.orderedContent()[0]
        if vTag_field.elementDeclaration.name().localName() != "vtag_field":
            raise Exception("vtag_field should be first element in the list!")
        jsonSubStruct['jausType'] = vTag_field.value.field_type_unsigned
        jsonSubStruct['minItems'] = vTag_field.value.min_count
        jsonSubStruct['maxItems'] = vTag_field.value.max_count
        jsonSubStruct['isVariant'] = True
        # add list elements
        for list_line in element.value.orderedContent():
            if list_line.elementDeclaration.name().localName() != "vtag_field":
                self.parse_element(list_line, jsonSubStruct,
                                   filename, depth + 1)

    def parse_variable_format_field(self, element, jsonStruct, filename, depth=1):
        name = self.get_name(element)
        comment = self.get_comment(element, prefix='')
        optional = self.parse_tag_optional(element)
        count_field = element.value.orderedContent()[1]
        if count_field.elementDeclaration.name().localName() != "count_field":
            raise Exception("JAUS MESSAGE should contain count_field!")
        jsonSubStruct = self.create_complex_struct(
            jsonStruct, name, 'object', optional, comment)
        jsonSubStruct['jausType'] = count_field.value.field_type_unsigned
        variable_format_field = element.value.orderedContent()[0]
        if variable_format_field.elementDeclaration.name().localName() != "format_field":
            raise Exception("JAUS MESSAGE should contain format_field!")
        if variable_format_field.value.format_enum:
            jsonFormatFieldStruct = self.create_simple_struct(jsonSubStruct, 'formatField', 'unsigned byte', False, "")
            formatField = []
            valuesEnum = []
            for format_enum in variable_format_field.value.format_enum:
                enumConst = self.check_spaces(format_enum.field_format)
                formatField.append({'valueEnum': {
                    "enumIndex": self._to_int(format_enum.index, filename),
                    "enumConst": self.check_spaces(format_enum.field_format)
                }})
                valuesEnum.append(enumConst)
            jsonFormatFieldStruct['valueSet'] = formatField
            # exception with change the type to string to refer the enumeration in human readable manner
            if (len(valuesEnum) > 0):
                jsonFormatFieldStruct['type'] = 'string'
                jsonFormatFieldStruct['enum'] = valuesEnum
            jsonSubStruct['encapsulatedMessage'] = "sub"
            # append message ID definition
            for format_enum in variable_format_field.value.format_enum:
                self._add_payload_struct(format_enum.field_format, jsonSubStruct, False, comment, depth)
            # append generic message struct
            self.create_complex_struct(jsonSubStruct, 'payload', 'object', False, comment)

    def parse_bit_field(self, element, jsonStruct, filename, depth=1, declared_name='', declared_comment='', declared_optional=False):
        name = self.get_name(element, force=declared_name)
        comment = self.get_comment(element, prefix='', force=declared_comment)
        optional = self.parse_tag_optional(element, force=declared_optional)

        fieldType = element.value.field_type_unsigned
        jsonSubStruct = self.create_complex_struct(
            jsonStruct, name, 'object', optional, comment)
        jsonSubStruct['bitField'] = fieldType

        # subFields = []
        for rc in element.value.orderedContent():
            if rc.elementDeclaration.name().localName() == "sub_field":
                # if hasattr(rc.value, "scale_range"):
                #     typeLength = self.get_field_type_length(fieldType)
                #     self.parse_scale_range(
                #         rc, typeLength, jsonSubStruct, filename)
                if hasattr(rc.value, "bit_range"):
                    bitFieldName = rc.value.name
                    from_index = int(rc.value.bit_range.from_index)
                    to_index = int(rc.value.bit_range.to_index)
                    jsonSubFieldStruct = self.create_simple_struct(
                        jsonSubStruct, bitFieldName, fieldType, optional, comment)
                    jsonSubFieldStruct['bitRange'] = {
                        "from": from_index,
                        "to": to_index
                    }
                    if hasattr(rc.value, "value_set"):
                        self.parse_value_set(
                            rc.value.value_set, jsonSubFieldStruct, filename)
                    # subFields.append(jsonSubFieldStruct)
                else:
                    logging.warning("no 'bit_range' in 'sub_field' found, message: %s, file: %s" % (
                        self._current_msg_name, filename))

        # jsonSubStruct['bitField'] = subFields

    def parse_fixed_length_string(self, element, jsonStruct, filename, depth=1, declared_name='', declared_comment='', declared_optional=False):
        name = self.get_name(element, force=declared_name)
        comment = self.get_comment(element, force=declared_comment)
        optional = self.parse_tag_optional(element, force=declared_optional)
        jsonSubStruct = self.create_simple_struct(
            jsonStruct, name, 'string', optional, comment)
        jsonSubStruct['minLength'] = element.value.string_length
        jsonSubStruct['maxLength'] = element.value.string_length

    def _add_payload_struct(self, field_type, jsonStruct, optional, comment, depth):
        if field_type in ["JAUS MESSAGE", "JAUS_MESSAGE"]:
            # add JAUS MESSAGE description
            jsonPayloadStruct = self.create_simple_struct(
                jsonStruct, 'payloadMessageId', 'unsigned short integer', optional, 'message id of the payload message')
            jsonPayloadStruct['type'] = 'string'
        else:
            # add user defined struct
            if field_type in self._known_formats:
                (_element,
                 _filename) = self._known_formats[field_type]
                jsonPayloadStruct = self.create_complex_struct(
                    jsonStruct, 'payloadStruct', 'object', optional, comment)
                self.parse_element(
                    _element, jsonPayloadStruct, _filename, depth + 1)

    def parse_variable_length_field(self, element, jsonStruct, filename, depth=1):
        name = self.get_name(element)
        comment = self.get_comment(element)
        optional = self.parse_tag_optional(element)
        # read count field first
        count_field = element.value.orderedContent()[0]
        if count_field.elementDeclaration.name().localName() != "count_field":
            raise Exception(
                "variable_length_string should contain count_field!")
        jsonSubStruct = self.create_complex_struct(
            jsonStruct, name, 'object', optional, comment)
        jsonSubStruct['minLength'] = count_field.value.min_count
        if count_field.value.max_count:
            jsonSubStruct['maxLength'] = count_field.value.max_count
        jsonSubStruct['jausType'] = count_field.value.field_type_unsigned
        jsonSubStruct['fieldFormat'] = element.value.field_format
        jsonSubStruct['encapsulatedMessage'] = "simple"
        # append message ID definition
        self._add_payload_struct(element.value.field_format, jsonSubStruct, False, comment, depth)
        # append generic message struct
        self.create_complex_struct(jsonSubStruct, 'payload', 'object', False, comment)

    def parse_variable_length_string(self, element, jsonStruct, filename, depth=1, declared_name='', declared_comment='', declared_optional=False):
        name = self.get_name(element, force=declared_name)
        comment = self.get_comment(element, force=declared_comment)
        optional = self.parse_tag_optional(element, force=declared_optional)
        # read count field first
        count_field = element.value.orderedContent()[0]
        if count_field.elementDeclaration.name().localName() != "count_field":
            raise Exception(
                "variable_length_string should contain count_field!")
        jsonSubStruct = self.create_simple_struct(
            jsonStruct, name, 'string', optional, comment)
        jsonSubStruct['minLength'] = count_field.value.min_count if count_field.value.min_count else 0
        jsonSubStruct['maxLength'] = count_field.value.max_count if count_field.value.max_count else 2 ** (
            8 * self.get_field_type_length(count_field.value.field_type_unsigned))
        jsonSubStruct['jausType'] = count_field.value.field_type_unsigned

    def parse_list(self, element, jsonStruct, filename, depth=1, declared_name='', declared_comment='', declared_optional=False):
        name = self.get_name(element, force=declared_name)
        comment = self.get_comment(element, force=declared_comment)
        optional = self.parse_tag_optional(element, force=declared_optional)
        jsonSubStruct = self.create_complex_struct(
            jsonStruct, name, 'array', optional, comment)

        # read count field first
        count_field = element.value.orderedContent()[0]
        if count_field.elementDeclaration.name().localName() != "count_field":
            raise Exception("count_field should be first element in the list!")
        jsonSubStruct['jausType'] = count_field.value.field_type_unsigned
        jsonSubStruct['minItems'] = count_field.value.min_count
        jsonSubStruct['maxItems'] = count_field.value.max_count
        jsonSubStruct['isVariant'] = False
        # add list elements
        for list_line in element.value.orderedContent():
            if list_line.elementDeclaration.name().localName() != "count_field":
                self.parse_element(list_line, jsonSubStruct,
                                   filename, depth + 1)

    def parse_presence_vector(self, element, jsonStruct, filename, depth=1):
        elType = element.value.field_type_unsigned
        jsonSubStruct = self.create_simple_struct(
            jsonStruct, 'presenceVector', elType, False, '')

    def parse_fixed_field(self, element, jsonStruct, filename, depth=1, declared_name='', declared_comment='', declared_optional=False):
        name = self.get_name(element, force=declared_name)
        comment = self.get_comment(element, prefix='', force=declared_comment)
        optional = self.parse_tag_optional(element, force=declared_optional)

        fieldType = element.value.field_type
        jsonSubStruct = self.create_simple_struct(
            jsonStruct, name, fieldType, optional, comment)
        # an exception to set the message ID
        if name == 'MessageID':
            jsonSubStruct['type'] = 'string'
            jsonSubStruct['const'] = self.msgIdHex

        # TODO eval scale_range in fixed_field
        for rc in element.value.orderedContent():
            if rc.elementDeclaration.name().localName() == "scale_range":
                typeLength = self.get_field_type_length(fieldType)
                self.parse_scale_range(rc, typeLength, jsonSubStruct, filename)
            elif rc.elementDeclaration.name().localName() == "value_set":
                self.parse_value_set(rc.value, jsonSubStruct, filename)
            else:
                raise Exception(
                    f"skipped '{rc.elementDeclaration.name().localName()}' in 'fixed_field' -- not implemented, message: {self._current_msg_name}, file: {filename}")

    def parse_declared_array(self, element, jsonStruct, filename, depth=1):
        js, incFile = self._resolve_type_ref(
            element.value.declared_type_ref, "array", filename)
        return self.parse_array(js, jsonStruct, incFile, depth, element.value.name, self.get_comment(element), self.parse_tag_optional(element))

    def parse_declared_bit_field(self, element, jsonStruct, filename, depth=1):
        js, incFile = self._resolve_type_ref(
            element.value.declared_type_ref, "bit_field", filename)
        return self.parse_bit_field(js, jsonStruct, incFile, depth, element.value.name, self.get_comment(element), self.parse_tag_optional(element))

    def parse_declared_fixed_field(self, element, jsonStruct, filename, depth=1):
        js, incFile = self._resolve_type_ref(
            element.value.declared_type_ref, "fixed_field", filename)
        return self.parse_fixed_field(js, jsonStruct, incFile, depth, element.value.name, self.get_comment(element), self.parse_tag_optional(element))

    def parse_declared_list(self, element, jsonStruct, filename, depth=1):
        js, incFile = self._resolve_type_ref(
            element.value.declared_type_ref, "list", filename)
        return self.parse_list(js, jsonStruct, incFile, depth, element.value.name, self.get_comment(element), self.parse_tag_optional(element))

    def parse_declared_record(self, element, jsonStruct, filename, depth=1):
        js, incFile = self._resolve_type_ref(
            element.value.declared_type_ref, "record", filename)
        self.parse_record(js, jsonStruct, incFile, depth,
                          element.value.name, self.get_comment(element), self.parse_tag_optional(element))

    def parse_declared_variable_length_string(self, element, jsonStruct, filename, depth=1):
        js, incFile = self._resolve_type_ref(
            element.value.declared_type_ref, "variable_length_string", filename)
        return self.parse_variable_length_string(js, jsonStruct, incFile, depth, element.value.name, self.get_comment(element), self.parse_tag_optional(element))

    def parse_variable_field(self, element, jsonStruct, filename, depth=1):
        name = self.get_name(element)
        comment = self.get_comment(element)
        optional = self.parse_tag_optional(element)
        jsonSubStruct = self.create_complex_struct(
            jsonStruct, name, 'array', optional, comment)
        # add enum elements
        for rc in element.value.orderedContent():
            if rc.elementDeclaration.name().localName() != "type_and_units_field":
                logging.warning(
                    f"Skipped unexpected child '{rc.elementDeclaration.name().localName()}' for variable_field in {filename}")
            else:
                jsonSubStruct['jausType'] = 'unsigned byte'
                jsonSubStruct['minItems'] = 1
                jsonSubStruct['maxItems'] = 1
                for val in rc.value.orderedContent():
                    if val.elementDeclaration.name().localName() == "type_and_units_enum":
                        fieldName = self.get_name(val)
                        fieldType = val.value.field_type
                        jsonTypeUnitStruct = self.create_simple_struct(
                            jsonSubStruct, fieldName, fieldType, True, '')
                        jsonTypeUnitStruct['fieldIndex'] = val.value.index
                        jsonTypeUnitStruct['fieldUnits'] = val.value.field_units
                        for valSet in val.value.orderedContent():
                            if valSet.elementDeclaration.name().localName() == "value_set":
                                self.parse_value_set(
                                    valSet, jsonTypeUnitStruct, filename)
                            elif valSet.elementDeclaration.name().localName() == "scale_range":
                                typeLength = self.get_field_type_length(
                                    fieldType)
                                self.parse_scale_range(
                                    valSet, typeLength, jsonTypeUnitStruct, filename)

    def parse_scale_range(self, element, q_type_length, jsonStruct, filename):
        bias = self._to_float(element.value.real_lower_limit, filename)
        real_upper_limit = self._to_float(
            element.value.real_upper_limit, filename)
        scale_factor = (real_upper_limit - bias) / (2**(q_type_length * 8) - 1)
        scaleRange = {
            "scaleFactor": scale_factor,
            "bias": bias
        }
        jsonStruct['scaleRange'] = scaleRange

    def parse_value_set(self, element, jsonStruct, filename):
        valueSet = []
        valuesEnum = []
        for value in element.orderedContent():
            elName = value.elementDeclaration.name().localName()
            if elName == 'value_enum':
                enumConst = self.check_spaces(value.value.enum_const)
                valueSet.append({'valueEnum': {
                    "enumIndex": self._to_int(value.value.enum_index, filename),
                    "enumConst": enumConst
                }})
                valuesEnum.append(enumConst)
            if elName == 'value_range':
                valueSet.append({'valueRange': {
                    "minimum": self._to_float(value.value.lower_limit, filename),
                    "maximum": self._to_float(value.value.upper_limit, filename),
                    "interpretation": value.value.interpretation if value.value.interpretation else ''
                }})
        jsonStruct['valueSet'] = valueSet
        # exception with change the type to string to refer the enumeration in human readable manner
        if (len(valuesEnum) > 0):
            jsonStruct['type'] = 'string'
            jsonStruct['enum'] = valuesEnum

    def get_field_type_length(self, field_type):
        f_types = {'byte': 1, 'short integer': 2, 'integer': 4, 'long integer': 8, 'unsigned byte': 1,
                   'unsigned short integer': 2, 'unsigned integer': 4, 'unsigned long integer': 8, 'float': 4, 'long float': 8}
        return f_types.get(field_type)

    def get_name(self, element, force=''):
        if force:
            return force
        return element.value.name

    def get_comment(self, element, prefix='', sep='', force=''):
        if force:
            return force
        comment = ''
        if element.value.interpretation:
            comment = self.check_spaces(element.value.interpretation)
            if prefix:
                comment = f"{prefix} {comment}"
            if comment and sep:
                comment = f"{sep} {comment}"
        return comment

    def check_spaces(self, data):
        if data:
            return " ".join(data.split())
        return ''

    def _resolve_type_ref(self, declared_type_ref, tagname, filename):
        js = self._get_doc(filename)
        path_list = declared_type_ref.split(".")
        # by one element we have the name of referenced item, search in `js` for tags with `tagname`
        if len(path_list) == 1:
            for tag in js.orderedContent():
                if tagname == tag.elementDeclaration.name().localName() and path_list[0] == tag.value.name:
                    return tag, filename
        else:
            # read first all defined references
            for declared_ref in js.declared_type_set_ref:
                if path_list[0] == declared_ref.name:
                    declared_id = declared_ref.id
                    declared_vers = declared_ref.version
                    logging.debug("declared_type_set_ref: id='%s', version='%s'" % (
                        declared_id, declared_vers))
                    ref_js = None
                    # try to find file with referenced set
                    incPath = None
                    for xml_file in self._local_first_xml_files():
                        ref_js = self._get_doc(xml_file)
                        if ref_js.id == declared_id and ref_js.version == declared_vers:
                            logging.debug("found referenced type for '%s' in '%s v%s', file: %s" % (
                                tagname, declared_id, declared_vers, xml_file))
                            incPath = xml_file
                            break
                    if ref_js is None:
                        raise Exception("Type reference not found: id='%s', version='%s'" % (
                            declared_id, declared_vers))
                    else:
                        return self._resolve_type_ref('.'.join(path_list[1:]), tagname, incPath)
        raise Exception("declared_type_ref '%s' not found in %s" %
                        (declared_type_ref, filename))

    def _resolve_const_ref(self, name, filename):
        js = self._get_doc(filename)
        path_list = name.split(".")
        # by one element we have the name of referenced item, search in `js` for tags with `tagname`
        if len(path_list) == 1:
            for tag in js.orderedContent():
                if 'const_def' == tag.elementDeclaration.name().localName() and path_list[0] == tag.value.name:
                    return tag.value.const_value, tag.value.const_type, filename
        else:
            # read first all defined references
            for declared_const_ref in js.declared_const_set_ref:
                if path_list[0] == declared_const_ref.name:
                    declared_id = declared_const_ref.id
                    declared_vers = declared_const_ref.version
                    logging.debug("declared_const_ref: id='%s', version='%s'" % (
                        declared_id, declared_vers))
                    ref_js = None
                    # try to find file with referenced set
                    incPath = None
                    for xml_file in self._local_first_xml_files():
                        ref_js = self._get_doc(xml_file)
                        if ref_js.id == declared_id and ref_js.version == declared_vers:
                            logging.debug("found referenced const '%s v%s' in %s" % (
                                declared_id, declared_vers, xml_file))
                            incPath = xml_file
                            break
                    if ref_js is None:
                        raise Exception("declared_const_ref not found: id='%s', version='%s'" % (
                            declared_id, declared_vers))
                    else:
                        return self._resolve_const_ref('.'.join(path_list[1:]), incPath)
        raise Exception("declared_const_ref '%s' not found in %s" %
                        (name, filename))

    def _local_first_xml_files(self):
        # search in current directory first!
        return [f for f in self.xml_files if f.startswith(self.dirname)] + [f for f in self.xml_files if not f.startswith(self.dirname)]

    def _to_float(self, value, filename):
        try:
            return float(value)
        except ValueError:
            rVal = value
            # find variables in values
            re_vars = re.compile(r"(?P<name>[a-zA-Z]+[^\*\-\+\/]*)")
            for var in re_vars.findall(value):
                # replace all known variables
                const_val, _const_type, _filename = self._resolve_const_ref(
                    var, filename)
                rVal = rVal.replace(var, const_val)
            # try to convert again
            ret = float(eval(rVal))
            logging.debug("resolved '%s' to '%s', evaluated to %.6f" %
                          (value, rVal, ret))
            return ret

    def _to_int(self, value, filename):
        try:
            return int(value)
        except ValueError:
            rVal = value
            # find variables in values
            re_vars = re.compile(r"(?P<name>[a-zA-Z]+[^\*\-\+\/]*)")
            for var in re_vars.findall(value):
                # replace all known variables
                const_val, _const_type, _filename = self._resolve_const_ref(
                    var, filename)
                rVal = rVal.replace(var, const_val)
            # try to convert again
            ret = int(eval(rVal))
            logging.debug("resolved '%s' to '%s', evaluated to %d" %
                          (value, rVal, ret))
            return ret

    def _get_doc(self, path):
        try:
            return self.doc_files[path]
        except KeyError:
            try:
                import jsidl_pyxb.jsidl as jsidl
            except (ImportError, ModuleNotFoundError):
                # try ROS environment
                import fkie_iop_json_generator.jsidl_pyxb.jsidl as jsidl
            try:
                with open(path) as f:
                    data = f.read()
                    jsDoc = jsidl.CreateFromDocument(data)
                    self.doc_files[path] = jsDoc
                    return jsDoc
            except Exception as e:
                import traceback
                print(traceback.format_exc())
                raise e
        return None
