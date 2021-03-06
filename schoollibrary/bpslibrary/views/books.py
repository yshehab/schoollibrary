"""Handle book repository functionalities."""

# pylint: disable=C0103

from urllib import request as urllib_request
from time import sleep
import re
import random
import sqlite3
from flask import Blueprint, flash, redirect, render_template, request
from flask_paginate import Pagination, get_page_parameter
from sqlalchemy import exc, or_
from bpslibrary import app
from bpslibrary.database import db_session
from bpslibrary.models import Author, Book, Category
from bpslibrary.utils.barcode import scan_for_isbn
from bpslibrary.utils.apihandler import APIClient
from bpslibrary.utils.permission import admin_access_required
from bpslibrary.utils.enums import BookLocation
from bpslibrary.views.loans import init_loan_forms

mod = Blueprint('books', __name__, url_prefix='/books')
THUMBNAILS_ABSOLUTE_DIR = app.config['THUMBNAILS_ABSOLUTE_DIR']
THUMBNAILS_DIR = app.config['THUMBNAILS_DIR']
PER_PAGE = app.config['PER_PAGE']


@mod.route('/')
def index():
    """Render the default landing page for books."""
    return view_books()


@mod.route('/lookup', methods=['GET', 'POST'])
@admin_access_required
def lookup_book():
    """Look up book details online."""
    if request.method == 'GET':
        return render_template('add_book.html')

    if request.method == 'POST':
        found_books = []
        isbns = set()
        barcode_isbn = []
        input_isbn = request.form['isbn'].strip().split(',')
        book_title = request.form['book_title'].strip()
        barcode_file = None
        try:
            if 'barcode' in request.files:
                barcode_file = request.files['barcode']
                if not barcode_file.filename == '':
                    barcode_isbn = scan_for_isbn(barcode_file)

            if barcode_isbn or input_isbn or book_title:
                isbns = set(input_isbn + barcode_isbn)
                isbns.discard('')
                api_client = APIClient(isbns, book_title)
                found_books = api_client.find_books()

        except ValueError as e:
            flash("Something has gone wrong! <br>" + str(e), 'error')

        return render_template('add_book.html',
                               found_books=found_books,
                               search_title=book_title,
                               search_isbn=','.join(isbns)
                               if bool(isbns) else '')


@mod.route('/add', methods=['POST'])
@admin_access_required
def add_book():
    """Add a book to the library."""
    try:
        book = Book()
        # defaults
        book.is_available = True
        book.current_location = BookLocation.LIBRARY.value

        book.title = request.form['book_title'].strip()
        book.isbn10 = request.form['isbn10'].strip()
        book.isbn13 = request.form['isbn13'].strip()
        book.description = request.form['book_description'].strip()
        book.preview_url = request.form['preview_url'].strip()

        for author_name in request.form['book_authors'].split(','):
            author_name = author_name.strip()
            author = Author.query.filter(Author.name == author_name).first()
            if not author:
                author = Author(author_name)
            book.authors.append(author)

        for category_name in request.form['book_categories'].split(','):
            category_name = category_name.strip()
            category = Category.query.\
                filter(Category.name == category_name).first()
            if not category:
                category = Category(category_name)
            book.categories.append(category)

        book.thumbnail_url = request.form['thumbnail_url'].strip()
        if book.thumbnail_url:
            title = [c for c in book.title.replace(' ', '_')
                     if re.match(r'\w', c)]
            image_name = ''.join(title) + book.isbn13 + '.jpg'

            img = open(THUMBNAILS_ABSOLUTE_DIR + image_name, 'wb')
            img.write(urllib_request.urlopen(book.thumbnail_url).read())
            book.image_name = image_name

        session = db_session()
        session.add(book)
        session.commit()

        flash("The book has been added to the library successfully!")
    except RuntimeError as rte:
        error_message = "Something has gone wrong!"
        if isinstance(rte, exc.IntegrityError):
            error_message += "<br>It seems that the book '%s' "\
                "already exists in the library." % book.title

        flash(error_message, 'error')

    return render_template('add_book.html')


def validate_add_book():
    """Validate books on addition or modification."""
    return None


@mod.route('/edit', methods=['GET', 'POST'])
@admin_access_required
def edit_book():
    """Update a book in the library."""
    session = db_session()

    lookup_isbns = []
    lookup_titles = []
    books = session.query(Book).distinct().\
        values(Book.isbn10,
               Book.isbn13,
               Book.title)

    for book in books:
        if book[0]:
            lookup_isbns.append(book[0])
        if book[1]:
            lookup_isbns.append(book[1])
        if book[2]:
            lookup_titles.append(book[2])

    if lookup_isbns:
        lookup_isbns.sort()
    if lookup_titles:
        lookup_titles.sort()

    if request.method == 'GET':
        return render_template('edit_book.html',
                               lookup_isbns=lookup_isbns,
                               lookup_titles=lookup_titles)

    found_books = []

    if request.method == 'POST':
        search_isbn = request.form['search_isbn']
        search_title = request.form['search_title']

        if search_title and search_title.strip():
            search_term = '%' + search_title.strip() + '%'
            found_books = session.query(Book).\
                filter(Book.title.ilike(search_term)).all()

        if search_isbn and search_isbn.strip():
            search_term = '%' + search_isbn.strip() + '%'
            found_books = found_books + session.query(Book).\
                filter(or_(Book.isbn10.ilike(search_term),
                           Book.isbn13.ilike(search_term))).all()

    result = render_template('edit_book.html',
                             lookup_isbns=lookup_isbns,
                             lookup_titles=lookup_titles,
                             search_isbn=search_isbn,
                             search_title=search_title,
                             thumbnails_dir=THUMBNAILS_DIR,
                             found_books=sorted(found_books,
                                                key=lambda b: b.title))
    return result


@mod.route('/update', methods=['POST'])
@admin_access_required
def update_book():
    """Update a book with provided details."""
    try:
        session = db_session()

        update_id = request.form['book_id']
        update_status = int(request.form['book_status'].strip())
        update_title = request.form['book_title'].strip()
        update_description = request.form['book_description'].strip()
        update_thumbnail_url = request.form['book_thumbnail_url'].strip()
        update_preview_url = request.form['book_preview_url'].strip()
        update_categories = [c.strip() for c
                             in request.form['book_categories'].split(',')]
        update_authors = [a.strip() for a
                          in request.form['book_authors'].split(',')]

        book = session.query(Book).filter(Book.id == update_id).first()

        book.title = update_title
        book.description = update_description
        book.is_available = update_status

        # update categories
        # removed
        for category in book.categories:
            if category.name not in update_categories:
                book.categories.remove(category)
        # added
        for category_name in update_categories:
            if category_name not in [c.name for c in book.categories]:
                book.categories.append(Category(category_name))

        # update authors
        # removed
        for author in book.authors:
            if author.name not in update_authors:
                book.authors.remove(author)
        # added
        for author_name in update_authors:
            if author_name not in [a.name for a in book.authors]:
                book.authors.append(Author(author_name))

        # thumbnail
        if update_thumbnail_url and book.thumbnail_url != update_thumbnail_url:
            book.thumbnail_url = update_thumbnail_url
            title = [c for c in book.title.replace(' ', '_')
                     if re.match(r'\w', c)]
            image_name = ''.join(title) + book.isbn13 + '.jpg'

            img = open(THUMBNAILS_ABSOLUTE_DIR + image_name, 'wb')
            img.write(urllib_request.urlopen(book.thumbnail_url).read())
            book.image_name = image_name

        # preview url
        if update_preview_url and book.preview_url != update_preview_url:
            book.preview_url = update_preview_url

        session.commit()

        flash("The book has been updated successfully!")
    except RuntimeError as rte:
        flash("Something has gone wrong! <br>%s" % str(rte), 'error')

    return redirect('books/edit')


@mod.route('/view', methods=['GET'])
def view_books(ready_books=None):
    """Display books in the library.

    Defaults to displaying available books only.
    If `include_unavailable` parameter is set in the `request`,
    it display all books; this is used in the admin view.
    """
    session = db_session()

    # get search cache
    search_cache = []

    for book_title in session.query(Book.title).distinct():
        search_cache.append(book_title[0])

    for category_name in session.query(Category.name).distinct():
        search_cache.append(category_name[0])

    for author_name in session.query(Author.name).distinct():
        search_cache.append(author_name[0])

    search_cache.sort()

    # initialise loan forms
    new_loan_form, loan_return_form = init_loan_forms()

    # requpest parameters
    page = request.args.get(get_page_parameter(), type=int, default=1)
    include_unavailable = request.args.get('include-unavailable')
    search_term = request.args.get('q')

    # if books have been provided, display them
    if ready_books:
        total = len(ready_books)
        books = ready_books
    # apply search criteria if provided
    elif search_term:
        search_term = '%' + search_term.strip() + '%'
        total = session.query(Book).\
            join(Author.books).\
            filter(or_(Book.title.ilike(search_term),
                       Author.name.ilike(search_term))).\
            union(
                session.query(Book).
                join(Category.books).
                filter(or_(Book.title.ilike(search_term),
                           Category.name.ilike(search_term)))
            ).count()
        books = session.query(Book).\
            join(Author.books).\
            filter(or_(Book.title.ilike(search_term),
                       Author.name.ilike(search_term))).\
            union(
                session.query(Book).
                join(Category.books).
                filter(or_(Book.title.ilike(search_term),
                           Category.name.ilike(search_term)))
            ).order_by(Book.title).\
            limit(PER_PAGE).offset((page - 1) * PER_PAGE)
    # include all books if specified
    elif include_unavailable:
        total = session.query(Book.id).count()
        books = session.query(Book).order_by(Book.title).\
            limit(PER_PAGE).offset((page - 1) * PER_PAGE)
    # in all other cases, display all vailable books
    else:
        total = session.query(Book).filter(Book.is_available == 1).count()
        books = session.query(Book).filter(Book.is_available == 1).\
            order_by(Book.title).limit(PER_PAGE).offset((page - 1) * PER_PAGE)

    pagination = Pagination(page=page,
                            total=total,
                            per_page=PER_PAGE,
                            css_framework="bootstrap3")

    return render_template('view_book.html',
                           books=books,
                           new_loan_form=new_loan_form,
                           loan_return_form=loan_return_form,
                           pagination=pagination,
                           search_cache=search_cache,
                           thumbnails_dir=THUMBNAILS_DIR)


@mod.route('/find', methods=['POST'])
def find_books():
    """Find books in the library based on the search term.

    Search term can be a full or partial book title, author name or
    category name.
    """
    search_term = request.form["search_term"]
    return redirect('books/view?q=' + search_term)


@mod.route('/autoload', methods=['GET', 'POST'])
def auto_load_books():
    """Automated book loading.

    Combining the lookup and add functions, this function aims at bulk
    loading of books in the background.
    """
    session = db_session()
    lookup_limit = request.args.get('n')

    # lookup books
    succeeded = []
    failed = []
    counter = 1

    try:
        for isbn in execute_sql('fetch_isbn', lookup_limit):
            # ensure we don't exceed google or amazon api usage limit
            if counter % 3 == 0:
                sleep(random.uniform(60, 90))
            else:
                sleep(random.uniform(5, 10))
            counter += 1

            api_client = APIClient(isbn, None)
            found_books = api_client.find_books(direct_search_only=True)

            # to ensure only the right book is added, only search resulting
            # yielding 1 result is accepted.
            if len(found_books) != 1:
                failed.append(
                    (isbn[0], "search results %d" % len(found_books)))
                continue

            # now we add the book.
            book = found_books[0]

            # defaults
            book.is_available = True
            book.current_location = BookLocation.LIBRARY.value

            if book.thumbnail_url:
                image_name = ''.join(
                    [c for c in book.title.replace(' ', '_')
                     if re.match(r'\w', c)]) + book.isbn13 + '.jpg'
                img = open(THUMBNAILS_ABSOLUTE_DIR + image_name, 'wb')
                img.write(urllib_request.urlopen(book.thumbnail_url).read())
                book.image_name = image_name

            for i in range(len(book.authors)):
                lookup_author = Author.query.filter(
                    Author.name == book.authors[i].name).first()
                if lookup_author:
                    book.authors[i] = None
                    book.authors[i] = lookup_author

            for i in range(len(book.categories)):
                lookup_category = Category.query.filter(
                    Category.name == book.categories[i].name).first()
                if lookup_category:
                    book.categories[i] = None
                    book.categories[i] = lookup_category

            session.add(book)
            session.commit()
            succeeded.append(isbn[0])

        execute_sql('update_success', succeeded=succeeded)
        execute_sql('update_failed', failed=failed)

    except RuntimeError as rt_error:
        flash("Something has gone wrong! " + str(rt_error))

    flash('success: ' + ','.join(str(i) for i in succeeded))
    flash('failed: ' + ','.join(str(i) for i, e in failed))
    return redirect('books/view')


def execute_sql(action, lookup_limit=10, failed=None, succeeded=None):
    """Execute sql to fetch isbns to lookup or update lookup status."""
    # update the lookup table
    connection = sqlite3.connect(
        app.config['DATABASE_URI'].replace('sqlite:///', ''))
    cursor = connection.cursor()
    sql = ""
    if action == 'fetch_isbn':
        sql = """
            SELECT DISTINCT isbn
            FROM isbn_lookup
            WHERE status IS NULL
            OR status NOT LIKE '%SUCCESS%'
            ORDER BY last_check
            LIMIT {0};
            """.format(int(lookup_limit))
        cursor.execute(sql)
        return cursor.fetchall()

    if action == 'update_success':
        assert (succeeded is not None), "Succeeded list is None."
        sql = """
            UPDATE isbn_lookup
            SET
                status = 'SUCCESS_DIRECT',
                last_check = CURRENT_TIMESTAMP
            WHERE isbn in ('{0}');
            """.format("','".join(str(i) for i in succeeded))
        cursor.execute(sql)
        connection.commit()

    if action == 'update_failed':
        # assert (failed is not None), "Failed list is None."
        # assert (failed), "Failed list is empty."
        if failed:
            sql = """
                UPDATE isbn_lookup
                    SET errors = (CASE isbn """
            for isbn, error in failed:
                sql += " WHEN '%s' THEN errors + '|%s' " % (isbn, error)
            sql += """ ELSE errors END),
                last_check = CURRENT_TIMESTAMP,
                status = 'FAILED_DIRECT'
                WHERE isbn IN ('%s');""" % "','".join(
                    [str(i) for i, e in failed])
            cursor.execute(sql)
            connection.commit()

    connection.close()
