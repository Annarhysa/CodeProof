import pytest

from backend.app.github import GitHubError, parse_issue_url


def test_parse_issue_url_valid():
    owner, repo, number = parse_issue_url("https://github.com/octocat/Hello-World/issues/42")
    assert (owner, repo, number) == ("octocat", "Hello-World", 42)


def test_parse_issue_url_trailing_slash():
    owner, repo, number = parse_issue_url("https://github.com/octocat/Hello-World/issues/42/")
    assert (owner, repo, number) == ("octocat", "Hello-World", 42)


@pytest.mark.parametrize("bad_url", [
    "https://github.com/octocat/Hello-World",
    "https://github.com/octocat/Hello-World/pull/42",
    "not a url",
    "https://gitlab.com/octocat/Hello-World/issues/42",
])
def test_parse_issue_url_rejects_non_issue_urls(bad_url):
    with pytest.raises(GitHubError):
        parse_issue_url(bad_url)
