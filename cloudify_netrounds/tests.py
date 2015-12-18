# Copyright (c) 2015 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from cloudify import ctx
from cloudify.decorators import operation
from cloudify import exceptions as cfy_exc

import datetime
import time
import xmlrpclib


TESTGROUP_ID = "testgroup_id"


def _get_probe_id(name, genalyzer_list):
    """return probe id by name"""
    if not name:
        raise cfy_exc.NonRecoverableError(
            "probe name must be specified"
        )
    for probe in genalyzer_list:
        if probe['name'] == name:
            return probe['id']
    raise cfy_exc.NonRecoverableError(
        "Unknow probe"
    )


def _get_script_id(script_list, package, name):
    """return script_id by name and package"""
    if not package:
        raise cfy_exc.NonRecoverableError(
            "script name must be specified"
        )
    if not name:
        raise cfy_exc.NonRecoverableError(
            "script name must be specified"
        )
    for script in script_list:
        if script['package'] == package and script['name'] == name:
            return script['id']
    raise cfy_exc.NonRecoverableError(
        "Unknow test script"
    )


def _update_input_values(values, genalyzer_list):
    """replace genalyzer name in any dict by probe_id (genalyzer_id)"""
    for key in values:
        if isinstance(values[key], dict):
            probe = values[key]
            if 'genalyzer' in probe:
                probe["genalyzer_id"] = _get_probe_id(
                    probe['genalyzer'], genalyzer_list
                )
                del probe['genalyzer']


def _update_ids(properties, genalyzer_list, script_list):
    """update script and probe name by real ids"""
    if 'tests' not in properties:
        return
    for test in properties['tests']:
        # fix id for test
        if test.get('id', 'None') == 'None':
            # for such case netrounds will generate new id
            test['id'] = None
        # update script_* by real id
        if 'script_name' in test or 'script_package' in test:
            test['script_id'] = _get_script_id(
                script_list, test['script_package'], test['script_name']
            )
            del test['script_package']
            del test['script_name']
        # update inputs, replace name to real probe_id
        if 'inputvalues' in test:
            _update_input_values(
                test['inputvalues'], genalyzer_list
            )


def _login_to():
    """login to netrounds"""
    auth = ctx.node.properties['auth']

    ctx.logger.info("login by {0} to https://app.netrounds.com/{1}/".format(
        auth['email'],
        auth['domain']
    ))

    url = "https://%s:%s@app.netrounds.com/%s/api/xmlrpc/" % (
        auth['email'], auth['password'], auth['domain']
    )

    return xmlrpclib.ServerProxy(url, allow_none=True)


def _validate_and_create_test_group(netrounds):
    """check inpurs and generate testgroup"""
    if not ctx.node.properties.get("tests"):
        raise cfy_exc.NonRecoverableError(
            "test list must be specified"
        )

    if not ctx.node.properties.get("name"):
        raise cfy_exc.NonRecoverableError(
            "name must be specified"
        )

    ctx.logger.info("get probes list")

    genalyzer_list = netrounds.genalyzer_list()

    ctx.logger.info("get script types list")

    script_list = netrounds.testing_script_list()

    testgroup_config = {
        "name": ctx.node.properties["name"],
        "description": ctx.node.properties.get("description", ""),
        "tests": ctx.node.properties["tests"]
    }

    ctx.logger.info("try to generate test group")
    _update_ids(testgroup_config, genalyzer_list, script_list)
    return testgroup_config


@operation
def create(**kwargs):
    """create new testgrop and run"""
    netrounds = _login_to()

    testgroup_config = _validate_and_create_test_group(netrounds)

    ctx.logger.info("create test group")

    testgroup_id = netrounds.testgroup_create(testgroup_config)
    ctx.instance.runtime_properties[TESTGROUP_ID] = testgroup_id

    status = netrounds.testgroup_get_status(testgroup_id)
    while status["status"] == "running":
        ctx.logger.info("run state is %s, let's wait" % status["status"])
        time.sleep(30)
        status = netrounds.testgroup_get_status(testgroup_id)

    test_id = status["tests"][0]["id"]

    results = netrounds.testing_get_results(test_id, None)

    ctx.logger.info("test result: {0}".format(
        str(results.get('results'))
    ))
    result_text = ['test logs:', '-----']
    for log_row in results.get('log', []):
        time_str = datetime.datetime.fromtimestamp(
            log_row['time']
        ).strftime('%Y-%m-%d %H:%M:%S')
        result_text += [
            "%s: %s" % (time_str, log_row['message'])
        ]
    result_text += ['-----']
    ctx.logger.info("\n".join(result_text))
    if status["status"] != 'passed':
        raise cfy_exc.NonRecoverableError(
            "Test failed!"
        )


@operation
def delete(**kwargs):
    """delete test group"""
    netrounds = _login_to()
    testgroup_id = ctx.instance.runtime_properties.get(TESTGROUP_ID)
    if testgroup_id:
        ctx.logger.info("Delete test group")
        netrounds.testgroup_delete([testgroup_id])


@operation
def creation_validation(**kwargs):
    """validate inputs by generate test group"""
    netrounds = _login_to()
    _validate_and_create_test_group(netrounds)
