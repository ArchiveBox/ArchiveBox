# browsertrix extractor

def save_browsertrix(link, out_dir, timeout, config):


	browsertrix_dir = out_dir / 'browsertrix'
	browsertrix_dir.mkdir(exist_ok=True)

	crawl_id = link.timestamp

	browsertrix_crawler_cmd = [
		'crawl',
		f'--url', link.url,
		f'--collection={crawl_id}',
		'--scopeType=page',
		'--generateWACZ',
		'--text=final-to-warc',
		'--timeLimit=60',
	]

	remote_cmd = """
	rm /tmp/dump.rdb;
	rm -rf /crawls/collections;
	mkdir /crawls/collections;
	env CRAWL_ID={crawl_id} 
	"""

	local_cmd = ['nc', 'browsertrix', '2222']

	status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(local_cmd, cwd=str(out_dir), input=remote_cmd, timeout=timeout)
		
		cmd_output = result.stdout.decode()

		wacz_output_file = Path('/browsertrix/crawls') / crawl_id / f'{crawl_id}'.wacz

		copy_and_overwrite(wacz_output_file, browsertrix_dir / wacz_output_file.name)



TEMPLATE = """

"""

# rm /tmp/dump.rdb;
# rm -rf /crawls/collections;
# mkdir /crawls/collections;
# env CRAWL_ID=tec2342 crawl --url 'https://example.com' --scopeType page --generateWACZ --collection tec2342 --text final-to-warc --timeLimit 60