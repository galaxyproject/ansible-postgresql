#!/usr/bin/env python
"""
Determine the latest version of the yum repository package.

usage: get_repo_rpm_version.py url distribution

e.g.:

get_repo_rpm_version.py http://yum.postgresql.org/9.2/redhat/rhel-6-x86_64/ centos
"""

import re
import sys
import urllib2

url, dist = sys.argv[1:]

try:
    repo = urllib2.urlopen(url)
except urllib2.HTTPError, e:
    print >>sys.stderr, "Failed to fetch directory list from %s" % url
    raise

pg_version = url.split('/')[3]
if pg_version[0] == "8" and dist != "sl":
    re_pattern = 'href=[\'"](pgdg-%s-%s-[\d+].noarch.rpm)[\'"]' % (dist, pg_version)
else:
    re_pattern = 'href=[\'"](pgdg-%s%s-%s-[\d+].noarch.rpm)[\'"]' % (dist, pg_version.replace('.', ''), pg_version)
match = re.findall(re_pattern, repo.read(), flags=re.I)

assert match, "No matching %s pgdg repository packages found for version %s at %s" % (dist, pg_version, url)

print match[0]

sys.exit(0)
