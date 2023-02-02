# Why does this file exist, and why not put this in `__main__`?
#
# You might be tempted to import things from `__main__` later,
# but that will cause problems: the code will get executed twice:
#
# - When you run `python -m git_changelog` python will execute
#   `__main__.py` as a script. That means there won't be any
#   `git_changelog.__main__` in `sys.modules`.
# - When you import `__main__` it will get executed again (as a module) because
#   there's no `git_changelog.__main__` in `sys.modules`.

"""Module that contains the command line application."""

from __future__ import annotations

import argparse
import sys

from jinja2.exceptions import TemplateNotFound

from git_changelog import templates
from git_changelog.build import Changelog

if sys.version_info < (3, 8):
    import importlib_metadata as metadata
else:
    from importlib import metadata  # noqa: WPS440

STYLES = ("angular", "atom", "conventional", "basic")


class Templates(tuple):  # noqa: WPS600 (subclassing tuple)
    """Helper to pick a template on the command line."""

    def __contains__(self, item: object) -> bool:
        if isinstance(item, str):
            return item.startswith("path:") or super().__contains__(item)
        return False


def get_version() -> str:
    """
    Return the current `git-changelog` version.

    Returns:
        The current `git-changelog` version.
    """
    try:
        return metadata.version("git-changelog")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def get_parser() -> argparse.ArgumentParser:
    """
    Return the CLI argument parser.

    Returns:
        An argparse parser.
    """
    parser = argparse.ArgumentParser(
        add_help=False,
        prog="git-changelog",
        description=re.sub(
            r"\n *",
            "\n",
            f"""
            Automatic Changelog generator using Jinja2 templates.

            This tool parses your commit messages to extract useful data
            that is then rendered using Jinja2 templates, for example to
            a changelog file formatted in Markdown.

            Each Git tag will be treated as a version of your project.
            Each version contains a set of commits, and will be an entry
            in your changelog. Commits in each version will be grouped
            by sections, depending on the commit style you follow.

            {BasicStyle._format_sections_help()}
            {AngularStyle._format_sections_help()}
            {ConventionalCommitStyle._format_sections_help()}
            """,  # noqa: WPS437
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "repository", metavar="REPOSITORY", nargs="?", default=".", help="The repository path, relative or absolute."
    )

    parser.add_argument(
        "-b",
        "--bump",
        action="store_true",
        dest="bump_latest",
        default=True,
        help="Guess the new latest version by bumping the previous one based on the set of unreleased commits. "
        "For example, if a commit contains breaking changes, bump the major number (or the minor number for 0.x versions). "
        "Else if there are new features, bump the minor number. Else just bump the patch number.",
    )
    parser.add_argument(
        "-h", "--help", action="help", default=argparse.SUPPRESS, help="Show this help message and exit."
    )
    parser.add_argument(
        "-i",
        "--in-place",
        action="store_true",
        dest="in_place",
        default=False,
        help="Insert new entries (versions missing from changelog) in-place. "
        "An output file must be specified. With custom templates, "
        "you must pass two additional arguments: --version-regex and --marker-line. "
        "When writing in-place, an 'inplace' variable "
        "will be injected in the Jinja context, "
        "allowing to adapt the generated contents "
        "(for example to skip changelog headers or footers).",
    )
    parser.add_argument(
        "-g",
        "--version-regex",
        action="store",
        dest="version_regex",
        default=None,
        help="A regular expression to match versions in the existing changelog "
        "(used to find the latest release) when writing in-place. "
        "The regular expression must be a Python regex with a 'version' named group. ",
    )

    parser.add_argument(
        "-m",
        "--marker-line",
        action="store",
        dest="marker_line",
        default=None,
        help="A marker line at which to insert new entries "
        "(versions missing from changelog). "
        "If two marker lines are present in the changelog, "
        "the contents between those two lines will be overwritten "
        "(useful to update an 'Unreleased' entry for example).",
    )
    parser.add_argument(
        "-o",
        "--output",
        action="store",
        dest="output",
        default=sys.stdout,
        help="Output to given file. Default: stdout.",
    )
    parser.add_argument(
        "-R",
        "--no-parse-refs",
        action="store_false",
        dest="parse_refs",
        default=True,
        help="Do not parse provider-specific references in commit messages (issues, PRs, etc.).",
    )
    parser.add_argument(
        "-s",
        "--style",
        choices=STYLES,
        default="basic",
        dest="style",
        help="The commit style to match against. Default: basic.",
    )
    parser.add_argument(
        "-S",
        "--sections",
        nargs="+",
        default=None,
        dest="sections",
        help="The sections to render. See the available sections for each supported style in the description.",
    )
    parser.add_argument(
        "-t",
        "--template",
        choices=Templates(("angular", "keepachangelog")),
        default="keepachangelog",
        dest="template",
        help='The Jinja2 template to use. Prefix with "path:" to specify the path '
        'to a directory containing a file named "changelog.md".',
    )
    parser.add_argument(
        "-T",
        "--trailers",
        action="store_true",
        default=False,
        dest="parse_trailers",
        help="Parse Git trailers in the commit message. See https://git-scm.com/docs/git-interpret-trailers.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version="%(prog)s " + get_version(),  # noqa: WPS323 (%)
        help="Show the current version of the program and exit.",
    )
    return parser


def _latest(lines: list[str], regex: Pattern) -> str | None:
    for line in lines:
        match = regex.search(line)
        if match:
            return match.groupdict()["version"]
    return None


def _unreleased(versions: list[Version], last_release: str):
    for index, version in enumerate(versions):
        if version.tag == last_release:
            return versions[:index]
    return versions


def main(args: list[str] | None = None) -> int:
    """
    Run the main program.

    This function is executed when you type `git-changelog` or `python -m git_changelog`.

    Arguments:
        args: Arguments passed from the command line.

    Returns:
        An exit code.
    """
    parser = get_parser()
    opts = parser.parse_args(args=args)

    # get template
    if opts.template.startswith("path:"):
        path = opts.template.replace("path:", "", 1)
        try:
            template = templates.get_custom_template(path)
        except TemplateNotFound:
            print(f"git-changelog: no such directory, or missing changelog.md: {path}", file=sys.stderr)
            return 1
    else:
        template = templates.get_template(opts.template)

    # build data
    changelog = Changelog(
        opts.repository,
        style=opts.style,
        parse_provider_refs=opts.parse_refs,
        parse_trailers=opts.parse_trailers,
    )

    # get rendered contents
    rendered = template.render(changelog=changelog)

    # write result in specified output
    if opts.output is sys.stdout:
        sys.stdout.write(rendered)
    else:
        with open(opts.output, "w") as stream:
            stream.write(rendered)

    return 0
