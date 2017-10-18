from util import (
    domain,
    base_url,
    get_str_between,
    get_link_type,
)
   

def validate_links(links):
    links = valid_links(links)       # remove chrome://, about:, mailto: etc.
    links = uniquefied_links(links)  # fix duplicate timestamps, returns sorted list
    links = sorted_links(links)      # deterministically sort the links
    
    if not links:
        print('[X] No links found :(')
        raise SystemExit(1)

    return list(links)

def sorted_links(links):
    return sorted(
        links,
        key=lambda link: (link['timestamp'], link['url']),
        reverse=True,
    )

def merge_links(link1, link2):
    longer = lambda a, b, key: a[key] if len(a[key]) > len(b[key]) else b[key]
    earlier = lambda a, b, key: a[key] if a[key] < b[key] else b[key]
    
    url = longer(link1, link2, 'url')
    earliest_ts = earlier(link1, link2, 'timestamp')
    longest_title = longer(link1, link2, 'title')
    cleanest_title = link1['title'] if '://' not in link1['title'] else link2['title']
    link = {
        'url': url,
        'domain': domain(url),
        'base_url': base_url(url),
        'timestamp': earliest_ts,
        'tags': longer(link1, link2, 'tags'),
        'title': longest_title if '://' not in longest_title else cleanest_title,
        'sources': list(set(link1['sources'] + link2['sources'])),
    }
    link['type'] = get_link_type(link)
    return link

def uniquefied_links(sorted_links):
    """
    ensures that all non-duplicate links have monotonically increasing timestamps
    """

    seen_urls = {}
    seen_timestamps = set()

    lower = lambda url: url.lower().strip()
    without_www = lambda url: url.replace('://www.', '://', 1)
    without_trailing_slash = lambda url: url[:-1] if url[-1] == '/' else url.replace('/?', '?')

    for link in sorted_links:
        url = without_www(without_trailing_slash(lower(link['url'])))
        if url in seen_urls:
            # merge with any other links that share the same url
            link = merge_links(seen_urls[url], link)
        elif link['timestamp'] in seen_timestamps:
            # add with incremented timestamp if earlier link exist with same timestamp
            link['timestamp'] = next_uniq_timestamp(seen_timestamps, link['timestamp'])
        
        seen_urls[url] = link
        seen_timestamps.add(link['timestamp'])
    
    return seen_urls.values()

def valid_links(links):
    """remove chrome://, about:// or other schemed links that cant be archived"""
    return (
        link
        for link in links
        if any(link['url'].startswith(s) for s in ('http://', 'https://', 'ftp://'))
    )

def links_after_timestamp(links, timestamp=None):
    if not timestamp:
        yield from links
        return

    print('[.] [{}] Resuming...'.format(timestamp))
    for link in links:
        try:
            if float(link['timestamp']) <= float(timestamp):
                yield link
        except (ValueError, TypeError):
            print('Resume value and all timestamp values must be valid numbers.')

def next_uniq_timestamp(used_timestamps, timestamp):
    """resolve duplicate timestamps by appending a decimal 1234, 1234 -> 1234.1, 1234.2"""

    if timestamp not in used_timestamps:
        return timestamp

    if '.' in timestamp:
        timestamp, nonce = timestamp.split('.')
        nonce = int(nonce)
    else:
        nonce = 1

    new_timestamp = '{}.{}'.format(timestamp, nonce)

    while new_timestamp in used_timestamps:
        nonce += 1
        new_timestamp = '{}.{}'.format(timestamp, nonce)

    return new_timestamp
