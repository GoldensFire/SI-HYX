# -*- coding: utf-8 -*-
"""Тесты вспомогательной логики workers.py: ETA, atempo, парсеры, статик-хелперы."""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import io
import json

import pytest

import workers
from workers import (RealETACalculator, _build_atempo_chain, InfoWorker,
                     YtdlpWorker, ProcessWorker)

from si_hyx_parts.tests.test_workers_helpers.test_eta_pass1 import (
    TestEtaPass1,
    TestEtaPass2,
    TestAtempoChain,
    TestParseSubLangs,
    TestParseAudioLangs,
    TestIterStreamLines,
    TestInjectTiktokHeaders,
    TestHeightFromFmt,
    TestSanitizeName,
    TestPriorityFlag,
    TestChoosePixFmt,
    _FakeProbeResult,
)

from si_hyx_parts.tests.test_workers_helpers.test_bt709_color_args import (
    TestBt709ColorArgs,
    TestMeasureAtCrf,
    TestWantsMetricScore,
    TestMetricSamples,
    TestAvifPixFmt,
    TestTargetDims,
)

from si_hyx_parts.tests.test_workers_helpers.test_av1_encoder_args import (
    TestAv1EncoderArgs,
    TestTrimSeekArgs,
    TestOutSuffix,
    TestBuildAudioFilters,
    TestScaleVf,
    TestAfArg,
    TestMapAvArgs,
    TestFpsArgs,
)

from si_hyx_parts.tests.test_workers_helpers.test_avif_encode_cmd import (
    TestAvifEncodeCmd,
    TestAvifDownscaleSide,
    TestCropFromCounts,
    TestProcessMediaProfiles,
)
