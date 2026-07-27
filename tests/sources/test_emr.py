"""Testes para emr_instances.sources.emr"""

from __future__ import annotations

from unittest.mock import MagicMock

from emr_instances.sources import emr


def test_version_key() -> None:
    """Test parsing de version string."""
    assert emr._version_key("emr-7.13.0") == (7, 13, 0)
    assert emr._version_key("emr-6.10.0") == (6, 10, 0)
    assert emr._version_key("emr-7.9.1") == (7, 9, 1)
    assert emr._version_key("emr-7.13.0") > emr._version_key("emr-7.12.0")
    assert emr._version_key("emr-7.13.0") > emr._version_key("emr-6.10.0")


def test_latest_release_label() -> None:
    """Test obtenção do release label mais recente."""
    mock_emr = MagicMock()
    mock_emr.list_release_labels.return_value = {
        "ReleaseLabels": ["emr-6.10.0", "emr-7.0.0", "emr-7.13.0"],
        "Marker": None,
    }

    result = emr.latest_release_label(mock_emr)
    assert result == "emr-7.13.0"


def test_latest_release_label_paginated() -> None:
    """Test obtenção de release labels com paginação."""
    mock_emr = MagicMock()
    mock_emr.list_release_labels.side_effect = [
        {"ReleaseLabels": ["emr-6.10.0", "emr-7.0.0"], "Marker": "marker1"},
        {"ReleaseLabels": ["emr-7.13.0"], "Marker": None},
    ]

    result = emr.latest_release_label(mock_emr)
    assert result == "emr-7.13.0"
    assert mock_emr.list_release_labels.call_count == 2


def test_supported_instance_types() -> None:
    """Test obtenção de tipos de instância suportados."""
    mock_emr = MagicMock()
    mock_emr.list_supported_instance_types.return_value = {
        "SupportedInstanceTypes": [
            {"Type": "m5.large"},
            {"Type": "m5.xlarge"},
        ],
        "Marker": None,
    }

    result = emr.supported_instance_types(mock_emr, "emr-7.13.0")
    assert len(result) == 2
    assert result[0]["Type"] == "m5.large"
