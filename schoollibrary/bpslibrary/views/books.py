"""Handle book repository functionalities."""

# pylint: disable=C0103

from urllib import request as urllib_request
import re
from flask import Blueprint, flash, redirect, render_template, request
from flask_login import current_user
from flask_paginate import Pagination, get_page_parameter
from sqlalchemy import exc, or_
from bpslibrary import app
from bpslibrary.database import db_session
from bpslibrary.forms import NewLoanForm, LoanReturnForm
from bpslibrary.models import Author, Book, Category, Pupil
from bpslibrary.utils.barcode import scan_for_isbn
from bpslibrary.utils.apihandler import APIClient
from bpslibrary.utils.permission import admin_access_required


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
        book.is_available = 1
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

        thumbnail_url = request.form['thumbnail_url'].strip()
        if thumbnail_url:
            title = [c for c in book.title.replace(' ', '_')
                     if re.match(r'\w', c)]
            image_name = ''.join(title) + book.isbn13 + '.jpg'

            img = open(THUMBNAILS_ABSOLUTE_DIR + image_name, 'wb')
            img.write(urllib_request.urlopen(thumbnail_url).read())
            book.thumbnail_url = image_name

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

    if request.method == 'GET':
        lookup_isbns = []
        lookup_titles = []
        books = session.query(Book).distinct().\
            values(Book.isbn10,
                   Book.isbn13,
                   Book.title)

        for book in books:
            lookup_isbns.append(book[0])
            lookup_isbns.append(book[1])
            lookup_titles.append(book[2])

        lookup_isbns.sort()
        lookup_titles.sort()
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
                filter(Book.title.ilike(search_term))

        if search_isbn and search_isbn.strip():
            search_term = '%' + search_isbn.strip() + '%'
            found_books = found_books + session.query(Book).\
                filter(or_(Book.isbn10.ilike(search_term),
                           Book.isbn13.ilike(search_term)))

    result = render_template('edit_book.html',
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

        book_id = request.form['book_id']
        book_status = int(request.form['book_status'])

        session.query(Book).filter(Book.id == book_id).update(
            {Book.is_available: book_status},
            synchronize_session=False)
        session.commit()

        flash("The book has been updated successfully!")
    except RuntimeError as rte:
        flash("Something has gone wrong! <br>%s" % str(rte), 'error')

    return redirect('books/edit')


@mod.route('/view', methods=['GET'])
def view_books(books=None):
    """Display books in the library.

    Defaults to displaying available books only.
    If `include_unavailable` parameter is set in the `request`,
    it display all books; this is used in the admin view all.
    """
    session = db_session()

    search_terms = []

    for book_title in session.query(Book.title).distinct():
        search_terms.append(book_title[0])

    for category_name in session.query(Category.name).distinct():
        search_terms.append(category_name[0])

    for author_name in session.query(Author.name).distinct():
        search_terms.append(author_name[0])

    search_terms.sort()

    new_loan_form, loan_return_form = init_loan_forms()

    page = request.args.get(get_page_parameter(), type=int, default=1)
    include_unavailable = request.args.get('include-unavailable')
    search_term = request.args.get('q')
    if search_term:
        search_term = '%' + search_term + '%'
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
    elif include_unavailable:
        total = session.query(Book.id).count()
        books = session.query(Book).order_by(Book.title).\
            limit(PER_PAGE).offset((page - 1) * PER_PAGE)
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
                           search_terms=search_terms,
                           thumbnails_dir=THUMBNAILS_DIR)


@mod.route('/find', methods=['GET', 'POST'])
def find_books():
    """Find books in the library based on the search term.

    Search term can be a full or partial book title, author name or
    category name.
    """
    search_term = request.form["search_term"]
    if search_term:
        return redirect('books/view?q=' + search_term)
    else:
        return redirect('books/view')


def init_loan_forms():
    """Initialise a new_loan and loan_return forms."""
    session = db_session()

    new_loan_form = None
    loan_return_form = None

    if current_user.is_authenticated and current_user.classroom:
        new_loan_form = NewLoanForm()
        class_id = current_user.classroom.id
        new_loan_form.pupil_id.choices = \
            [(p[0], p[1]) for p in session.query(Pupil.id, Pupil.name).
             filter(Pupil.classroom_id == class_id)]
        loan_return_form = LoanReturnForm()

    return new_loan_form, loan_return_form
