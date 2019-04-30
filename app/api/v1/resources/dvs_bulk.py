"""
 Copyright (c) 2018 Qualcomm Technologies, Inc.                                                                      #
                                                                                                                     #
 All rights reserved.                                                                                                #
                                                                                                                     #
 Redistribution and use in source and binary forms, with or without modification, are permitted (subject to the      #
 limitations in the disclaimer below) provided that the following conditions are met:                                #
 * Redistributions of source code must retain the above copyright notice, this list of conditions and the following  #
   disclaimer.                                                                                                       #
 * Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the         #
   following disclaimer in the documentation and/or other materials provided with the distribution.                  #
 * Neither the name of Qualcomm Technologies, Inc. nor the names of its contributors may be used to endorse or       #
   promote products derived from this software without specific prior written permission.                            #
                                                                                                                     #
 NO EXPRESS OR IMPLIED LICENSES TO ANY PARTY'S PATENT RIGHTS ARE GRANTED BY THIS LICENSE. THIS SOFTWARE IS PROVIDED  #
 BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED #
 TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT      #
 SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR   #
 CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES LOSS OF USE,      #
 DATA, OR PROFITS OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,      #
 STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,   #
 EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.                                                                  #
"""

import os
import re
import magic
import tempfile
from shutil import rmtree
from flask_restful import request
from flask_apispec import MethodResource, doc, use_kwargs

from ..handlers.error_handling import *
from ..handlers.codes import RESPONSES, MIME_TYPES
from ..helpers.tasks import CeleryTasks
from ..schema.system_schemas import BulkSchema
from ..models.request import *
from ..models.summary import *


class AdminBulk(MethodResource):
    """Flask resource for DVS bulk request."""

    @doc(description="Verify Bulk IMEIs via file/tac request", tags=['bulk'])
    @use_kwargs(BulkSchema().fields_dict, locations=['query'])
    def post(self):
        """Start processing DVS bulk request in background (calls celery task)."""

        try:
            invalid_imeis = 0
            filtered_list = []
            file = request.files.get('file')
            if file:
                tempdir = tempfile.mkdtemp()
                filename = file.filename
                filepath = os.path.join(tempdir, file.filename)
                file.save(filepath)
                try:
                    mimetype = magic.from_file(filepath, mime=True)
                    if filename != '':
                        if mimetype in app.config['system_config']['allowed_file_types']['AllowedTypes'] and '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['system_config']['allowed_file_types']['AllowedExt']:  # validate file type
                            file = open(filepath, 'r')
                            imeis = list(set(line.strip() for line in file.read().split('\n') if line))
                            if imeis and int(app.config['system_config']['global']['MinFileContent']) <= len(imeis) <= int(app.config['system_config']['global']['MaxFileContent']):  # validate file content length
                                for imei in imeis:
                                    if re.match(r'^[a-fA-F0-9]{14,16}$', imei) is None:
                                        invalid_imeis += 1
                                    else:
                                        filtered_list.append(imei)
                                imeis_list = filtered_list
                                if imeis_list:
                                    response = (CeleryTasks.get_summary.s(imeis_list, invalid_imeis) |
                                                CeleryTasks.log_results.s(input=str(filename))).apply_async()
                                    summary_data = {
                                        "tracking_id": response.parent.id,
                                        "input": filename,
                                        "input_type": "file",
                                        "status": response.state
                                    }
                                    summary_record = Summary.create(summary_data)
                                    request_data = {
                                        "username": request.form.get('username'),
                                        "user_id": request.form.get('user_id'),
                                        "summary_id": summary_record
                                    }
                                    Request.create(request_data)
                                    data = {
                                        "message": "You can track your request using this id",
                                        "task_id": response.parent.id
                                    }
                                    return Response(json.dumps(data), status=RESPONSES.get('OK'), mimetype=MIME_TYPES.get('JSON'))
                                else:
                                    return custom_response("File contains malformed content",
                                                           status=RESPONSES.get('BAD_REQUEST'),
                                                           mimetype=MIME_TYPES.get('JSON'))
                            else:
                                return custom_response("File must have minimum "+str(app.config['system_config']['global']['MinFileContent'])+" or maximum "+str(app.config['system_config']['global']['MaxFileContent'])+" IMEIs.", status=RESPONSES.get('bad_request'), mimetype=MIME_TYPES.get('json'))
                        else:
                            return custom_response("System only accepts tsv/txt files.", RESPONSES.get('BAD_REQUEST'), MIME_TYPES.get('JSON'))
                    else:
                        return custom_response('No file selected.', RESPONSES.get('BAD_REQUEST'),
                                               MIME_TYPES.get('JSON'))
                finally:
                    rmtree(tempdir)

            else:  # check for tac if file not uploaded
                tac = request.form.get('tac')
                if tac:
                    if tac.isdigit() and len(tac) == int(app.config['system_config']['global']['TacLength']):
                        result = Summary.find_by_input(tac)
                        if result is not None:
                            tracking_id = result['tracking_id']
                            request_data = {
                                "username": request.form.get('username'),
                                "user_id": request.form.get('user_id'),
                                "summary_id": result['id']
                            }
                            Request.create(request_data)
                            if result['status']=="PENDING":
                                data = {
                                    "message": "You're request is already in process cannot process another request "
                                               "with same data. Track using this id,",
                                    "task_id": tracking_id
                                }
                                return Response(json.dumps(data), status=RESPONSES.get('OK'),
                                                mimetype=MIME_TYPES.get('JSON'))
                            elif result['status']=="SUCCESS":
                                data = {
                                    "message": "You're request is completed. Track using this id,",
                                    "task_id": tracking_id
                                }
                                return Response(json.dumps(data), status=RESPONSES.get('OK'),
                                                mimetype=MIME_TYPES.get('JSON'))
                            else:
                                imei = tac + str(app.config['system_config']['global']['MinImeiRange'])
                                imei_list = [str(int(imei) + x) for x in
                                             range(int(app.config['system_config']['global']['MaxImeiRange']))]
                                response = (CeleryTasks.get_summary.subtask(args=(imei_list, invalid_imeis), task_id=tracking_id) |
                                            CeleryTasks.log_results.s(input=tac)).apply_async()
                                summary_data = {
                                    "tracking_id": tracking_id,
                                    "input": tac,
                                    "status": response.state
                                }
                                Request.create(request_data)
                                Summary.update_failed_task_to_pending(summary_data)
                                data = {
                                    "message": "You can track your request using this id",
                                    "task_id": tracking_id
                                }
                                return Response(json.dumps(data), status=RESPONSES.get('OK'),
                                                mimetype=MIME_TYPES.get('JSON'))
                        else:
                            imei = tac + str(app.config['system_config']['global']['MinImeiRange'])
                            imei_list = [str(int(imei) + x) for x in range(int(app.config['system_config']['global']['MaxImeiRange']))]
                            response = (CeleryTasks.get_summary.s(imei_list, invalid_imeis) |
                                        CeleryTasks.log_results.s(input=tac)).apply_async()
                            summary_data = {
                                "tracking_id": response.parent.id,
                                "input": tac,
                                "input_type": "tac",
                                "status": response.state
                            }
                            summary_record = Summary.create(summary_data)
                            request_data = {
                                "username": request.form.get('username'),
                                "user_id": request.form.get('user_id'),
                                "summary_id": summary_record
                            }
                            Request.create(request_data)
                            data = {
                                "message": "You can track your request using this id",
                                "task_id": response.parent.id
                            }
                            return Response(json.dumps(data), status=RESPONSES.get('OK'), mimetype=MIME_TYPES.get('JSON'))
                    else:
                        return custom_response("Invalid TAC, Enter 8 digit TAC.", RESPONSES.get('BAD_REQUEST'), MIME_TYPES.get('JSON'))
                else:
                    return custom_response("Upload file or enter TAC.", status=RESPONSES.get('BAD_REQUEST'), mimetype=MIME_TYPES.get('JSON'))
        except Exception as e:
            app.logger.info("Error occurred while retrieving summary.")
            app.logger.exception(e)
            return custom_response("Failed to verify bulk imeis.", RESPONSES.get('SERVICE_UNAVAILABLE'), MIME_TYPES.get('JSON'))


