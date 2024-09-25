from archivebox.logging_util import log_shell_welcome_msg


if __name__ == '__main__':
    # load the rich extension for ipython for pretty printing
    # https://rich.readthedocs.io/en/stable/introduction.html#ipython-extension
    get_ipython().run_line_magic('load_ext', 'rich')
    
    # print the welcome message
    log_shell_welcome_msg()
