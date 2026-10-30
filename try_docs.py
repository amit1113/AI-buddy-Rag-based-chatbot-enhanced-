"""Command-line tester for the documents tool (step 1 only, no UI).

  python try_docs.py add my.pdf
  python try_docs.py list
  python try_docs.py ask "What does the report say about X?"
  python try_docs.py remove my.pdf
"""
import argparse

from tools.docs import DocsTool


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("add").add_argument("path")
    sub.add_parser("remove").add_argument("name")
    sub.add_parser("ask").add_argument("question")
    args = parser.parse_args()

    docs = DocsTool()

    if args.command == "add":
        count = docs.add_pdf(args.path)
        print(f"Added {count} chunks from {args.path}")
    elif args.command == "list":
        documents = docs.list_documents()
        if not documents:
            print("No documents yet.")
        for name, count in documents.items():
            print(f"{name}: {count} chunks")
    elif args.command == "remove":
        print("Removed." if docs.remove(args.name) else "No such document.")
    elif args.command == "ask":
        result = docs.ask(args.question)
        print(result["answer"])
        print("\nSources:")
        for src in result["sources"]:
            print(f"  {src['file']}, page {src['page']} (similarity {src['score']})")


if __name__ == "__main__":
    main()
