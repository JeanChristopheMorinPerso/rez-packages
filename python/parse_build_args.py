source = parser.add_mutually_exclusive_group(required=True)
source.add_argument(
    "--download-upstream",
    action="store_true",
    help="download the archive from the pinned upstream release",
)
source.add_argument(
    "--archive",
    metavar="PATH",
    help="use a local archive instead of accessing the network",
)

parser.add_argument(
    "--download-only",
    action="store_true",
    help="download or verify the archive without extracting it",
)
