#!/usr/bin/env python3
"""Install the bundled skill by symlink or copy; never touches runtime config."""
import argparse, shutil
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--target',default='~/.hermes/skills/seo-operator')
parser.add_argument('--copy',action='store_true')
args=parser.parse_args()
source=Path(__file__).resolve().parents[1]/'skills/seo-operator'
target=Path(args.target).expanduser()
if target.exists() or target.is_symlink():
    raise SystemExit('Target already exists: '+str(target))
target.parent.mkdir(parents=True,exist_ok=True)
if args.copy:shutil.copytree(source,target)
else:target.symlink_to(source,directory=True)
print(target)
