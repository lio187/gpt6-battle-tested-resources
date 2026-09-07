#!/usr/bin/env python3
"""Interactive local OAuth onboarding; token written outside the repository."""
import argparse,os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
ap=argparse.ArgumentParser();ap.add_argument('client_json',help='Google Desktop OAuth client JSON');args=ap.parse_args()
scopes=['https://www.googleapis.com/auth/webmasters.readonly','https://www.googleapis.com/auth/analytics.readonly']
flow=InstalledAppFlow.from_client_secrets_file(args.client_json,scopes)
creds=flow.run_local_server(port=0,open_browser=True)
root=Path.home()/'.config/seo-operator';root.mkdir(parents=True,exist_ok=True);root.chmod(0o700)
p=root/'google-token.json';fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as f:f.write(creds.to_json())
print('Token saved with mode 600. Set GOOGLE_OAUTH_TOKEN_FILE='+str(p)+' before running doctor or sync.')
