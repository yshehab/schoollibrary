from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base

engine = create_engine('sqlite:///bpslibrary/bpslibrary.db', echo=True)
db_session = scoped_session(sessionmaker(autocommit=False,
                                         autoflush=False,
                                         bind=engine))
Model = declarative_base(name='Model')
Model.query = db_session.query_property()

def init_db():
    from bpslibrary.models import Model
    Model.metadata.create_all(bind=engine)


