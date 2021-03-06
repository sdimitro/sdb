#
# Copyright 2019 Delphix
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# pylint: disable=missing-docstring

import pytest
import sdb

from tests.unit import invoke, MOCK_PROGRAM


def test_empty() -> None:
    line = 'address'

    ret = invoke(MOCK_PROGRAM, [], line)

    assert not ret


def test_single_object() -> None:
    line = 'addr global_int'

    ret = invoke(MOCK_PROGRAM, [], line)

    assert len(ret) == 1
    assert ret[0].value_() == 0xffffffffc0000000
    assert sdb.type_equals(ret[0].type_, MOCK_PROGRAM.type('int *'))


def test_plain_address() -> None:
    line = 'addr 0xffffffffc084eee0'

    ret = invoke(MOCK_PROGRAM, [], line)

    assert len(ret) == 1
    assert ret[0].value_() == 0xffffffffc084eee0
    assert sdb.type_equals(ret[0].type_, MOCK_PROGRAM.type('void *'))


def test_multiple_object() -> None:
    line = 'addr global_int 0xffffffffc084eee0 global_void_ptr'

    ret = invoke(MOCK_PROGRAM, [], line)

    assert len(ret) == 3
    assert ret[0].value_() == 0xffffffffc0000000
    assert sdb.type_equals(ret[0].type_, MOCK_PROGRAM.type('int *'))
    assert ret[1].value_() == 0xffffffffc084eee0
    assert sdb.type_equals(ret[1].type_, MOCK_PROGRAM.type('void *'))
    assert ret[2].value_() == 0xffff88d26353c108
    assert sdb.type_equals(ret[2].type_, MOCK_PROGRAM.type('void **'))


def test_piped_invocations() -> None:
    line = 'addr global_int | addr 0xffffffffc084eee0 global_void_ptr'

    ret = invoke(MOCK_PROGRAM, [], line)

    assert len(ret) == 3
    assert ret[0].value_() == 0xffffffffc0000000
    assert sdb.type_equals(ret[0].type_, MOCK_PROGRAM.type('int *'))
    assert ret[1].value_() == 0xffffffffc084eee0
    assert sdb.type_equals(ret[1].type_, MOCK_PROGRAM.type('void *'))
    assert ret[2].value_() == 0xffff88d26353c108
    assert sdb.type_equals(ret[2].type_, MOCK_PROGRAM.type('void **'))


def test_echo_pipe() -> None:
    line = 'addr 0xffffffffc084eee0 | addr global_void_ptr'

    ret = invoke(MOCK_PROGRAM, [], line)

    assert len(ret) == 2
    assert ret[0].value_() == 0xffffffffc084eee0
    assert sdb.type_equals(ret[0].type_, MOCK_PROGRAM.type('void *'))
    assert ret[1].value_() == 0xffff88d26353c108
    assert sdb.type_equals(ret[1].type_, MOCK_PROGRAM.type('void **'))


def test_global_not_found() -> None:
    line = 'addr bogus'

    with pytest.raises(sdb.SymbolNotFoundError) as err:
        invoke(MOCK_PROGRAM, [], line)

    assert err.value.symbol == 'bogus'
