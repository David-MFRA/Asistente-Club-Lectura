from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

def start():

    scheduler.start()