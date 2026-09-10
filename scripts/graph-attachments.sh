#!/bin/bash
# Download (or list) the attachments of one M365 message. The graph-mail.ts CLI
# has NO attachment verb -- it covers verify|list|headers|send only -- so this
# calls the Graph /messages/{id}/attachments endpoint directly with the same
# per-mailbox credentials file.
#
#   scripts/graph-attachments.sh store/.m365-innova-credentials <messageId> list
#   scripts/graph-attachments.sh store/.m365-innova-credentials <messageId> save store/inbox/valami
#
# The reported "size" is the base64 length, so the written file is ~3% smaller.
# That is normal, not truncation -- verify with `file` instead.
set -euo pipefail
C="${1:?creds file}"; MID="${2:?message id}"; MODE="${3:-list}"; OUT="${4:-.}"
get(){ grep -E "^$1=" "$C" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r'; }
TEN=$(get TENANT_ID); CID=$(get CLIENT_ID); SEC=$(get CLIENT_SECRET); MB=$(get MAILBOX)
TOK=$(curl -s -X POST "https://login.microsoftonline.com/$TEN/oauth2/v2.0/token" \
  --data-urlencode "client_id=$CID" --data-urlencode "client_secret=$SEC" \
  --data-urlencode "scope=https://graph.microsoft.com/.default" \
  --data-urlencode "grant_type=client_credentials" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
J=$(curl -s -H "Authorization: Bearer $TOK" \
  "https://graph.microsoft.com/v1.0/users/$MB/messages/$MID/attachments")
if [ "$MODE" = list ]; then
  echo "$J" | python3 -c 'import json,sys
d=json.load(sys.stdin)
if "error" in d: print("ERR", d["error"].get("code"), d["error"].get("message")); sys.exit(1)
for a in d.get("value",[]):
    print(a.get("name"),"|",a.get("contentType"),"|",a.get("size"),"| inline=",a.get("isInline"))'
else
  mkdir -p "$OUT"
  echo "$J" | OUT="$OUT" python3 -c 'import json,sys,base64,os,re
d=json.load(sys.stdin); out=os.environ["OUT"]
if "error" in d: print("ERR", d["error"].get("code")); sys.exit(1)
for a in d.get("value",[]):
    n=re.sub(r"[^A-Za-z0-9._-]","_", a.get("name") or a.get("id"))
    b=a.get("contentBytes")
    if not b: print("SKIP (no contentBytes, likely itemAttachment):", n); continue
    p=os.path.join(out,n); open(p,"wb").write(base64.b64decode(b))
    print(p, os.path.getsize(p))'
fi
