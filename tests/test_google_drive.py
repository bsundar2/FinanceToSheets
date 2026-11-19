from unittest.mock import MagicMock, patch

from src.external_services import google_drive

FILES = [
    {
        "id": "1",
        "name": "Portfolio_Positions.csv",
        "modifiedTime": "2026-10-21T00:00:00Z",
    },
    {
        "id": "2",
        "name": "Accounts_History (1).csv",
        "modifiedTime": "2026-10-20T00:00:00Z",
    },
    {"id": "3", "name": "Accounts_History.csv", "modifiedTime": "2026-09-01T00:00:00Z"},
]


def _service(files=FILES):
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {"files": files}
    return service


class TestFindLatestMatchingFile:
    def test_newest_name_match_ignoring_case(self):
        with patch.object(google_drive, "_get_drive_service", return_value=_service()):
            match = google_drive.find_latest_matching_file("folder", "HISTORY")
        assert match["id"] == "2"

    def test_none_when_nothing_matches(self):
        with patch.object(google_drive, "_get_drive_service", return_value=_service()):
            assert google_drive.find_latest_matching_file("folder", "statement") is None

    def test_asks_drive_for_the_folder_newest_first(self):
        service = _service()
        with patch.object(google_drive, "_get_drive_service", return_value=service):
            google_drive.find_latest_matching_file("abc", "history")
        kwargs = service.files.return_value.list.call_args.kwargs
        assert kwargs["q"] == "'abc' in parents and trashed = false"
        assert kwargs["orderBy"] == "modifiedTime desc"


class TestDownloadLatestMatchingFile:
    def test_downloads_the_match(self):
        with patch.object(
            google_drive, "_get_drive_service", return_value=_service()
        ), patch.object(google_drive, "download_file", return_value=b"csv") as download:
            assert (
                google_drive.download_latest_matching_file("folder", "history")
                == b"csv"
            )
        download.assert_called_once_with("2")

    def test_none_without_a_match(self):
        with patch.object(
            google_drive, "_get_drive_service", return_value=_service([])
        ):
            assert (
                google_drive.download_latest_matching_file("folder", "history") is None
            )
