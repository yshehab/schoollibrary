from flask import Flask
#from flask_bootstrap import Bootstrap


INST_PATH = '/schoollibrary/schoollibrary/bpslibrary'
app = Flask(__name__, instance_path=INST_PATH, instance_relative_config=True)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS']=False
app.config['BOOTSTRAP_USE_MINIFIED']=True
app.config['Debug']=True

from bpslibrary.database import init_db, db_session

init_db()

#import bhplibrary.views
#import bhplibrary.models

from bpslibrary.views import books, index
app.register_blueprint(books.mod)
app.register_blueprint(index.mod)

@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

if __name__ == '__main__':
    #Bootstrap(app)
    app.run()