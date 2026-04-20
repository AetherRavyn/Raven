import re

with open("app/cli/main.py", "r") as f:
    content = f.read()

edge_cmd = """
def cmd_edge_node(args):
    \"\"\"Runs as an edge device connected to SARAS.\"\"\"
    from app.cli.edge_node import run_edge_node
    run_edge_node(
        name=args.name,
        server=args.server,
        capabilities=args.capabilities,
        location=args.location,
        sensors=args.sensors
    )

def main():
"""

content = content.replace("def main():", edge_cmd)

edge_parser = """    parser_approve.add_argument("task_id", help="The ID of the task to approve")
    parser_approve.set_defaults(func=cmd_approve)

    parser_edge = subparsers.add_parser("edge-node", help="Run as an edge device connected to SARAS")
    parser_edge.add_argument("--name", required=True, help="Name of the edge node")
    parser_edge.add_argument("--server", default="http://localhost:8090", help="URL of the SARAS server")
    parser_edge.add_argument("--capabilities", default="bash,python", help="Comma separated list of capabilities")
    parser_edge.add_argument("--location", default="unknown", help="Location of the node")
    parser_edge.add_argument("--sensors", default="", help="Comma separated list of sensors")
    parser_edge.set_defaults(func=cmd_edge_node)

    args = parser.parse_args()"""

content = content.replace("""    parser_approve.add_argument("task_id", help="The ID of the task to approve")
    parser_approve.set_defaults(func=cmd_approve)

    args = parser.parse_args()""", edge_parser)

with open("app/cli/main.py", "w") as f:
    f.write(content)
