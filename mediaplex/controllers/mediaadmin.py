"""
Media Admin Controller
"""
import os
from urlparse import urlparse, urlunparse
from cgi import parse_qs
from PIL import Image
from datetime import datetime
from copy import copy
from tg import config, flash, url, request, redirect
from tg.decorators import paginate, expose, validate, require
from sqlalchemy import and_, or_
from sqlalchemy.orm import eagerload, undefer
from repoze.what.predicates import has_permission
from pylons import tmpl_context

from mediaplex.lib import helpers
from mediaplex.lib.helpers import expose_xhr
from mediaplex.lib.base import RoutingController
from mediaplex.model import DBSession, Media, MediaFile, Comment, Tag, Author, AuthorWithIP
from mediaplex.forms.admin import SearchForm
from mediaplex.forms.media import MediaForm, AlbumArtForm
from mediaplex.forms.comments import PostCommentForm

class MediaadminController(RoutingController):
    allow_only = has_permission('admin')

    @expose_xhr('mediaplex.templates.admin.media.index', 'mediaplex.templates.admin.media.index-table')
    @paginate('media', items_per_page=25)
    def index(self, page=1, search=None, **kw):
        media = DBSession.query(Media)\
            .filter(Media.status.excludes('trash'))\
            .options(undefer('comment_count'))\
            .order_by(Media.status.desc(), Media.created_on)
        if search is not None:
            like_search = '%%%s%%' % search
            media = media.filter(or_(
                Media.title.like(like_search),
                Media.description.like(like_search),
                Media.notes.like(like_search),
                Media.tags.any(Tag.name.like(like_search)),
            ))
        return dict(
            media=media,
            search=search,
            search_form=SearchForm(action=helpers.url_for()),
        )

    @expose('mediaplex.templates.admin.media.edit')
    def edit(self, id, **values):
        media = self._fetch_media(id)
        form = MediaForm(action=helpers.url_for(action='save', id=media.id), media=media)
        form_values = {
            'slug': media.slug,
            'title': media.title,
            'author_name': media.author.name,
            'author_email': media.author.email,
            'description': media.description,
            'tags': ', '.join([tag.name for tag in media.tags]),
            'notes': media.notes,
            'details': {
                'duration': helpers.duration_from_seconds(media.duration),
                'url': u''
            },
        }

        album_art_form_errors = {}
        if tmpl_context.action == 'save_album_art':
            album_art_form_errors = tmpl_context.form_errors

        if media.id == 'new' and not media.notes:
            form_values['notes'] = """Bible References: None
S&H References: None
Reviewer: None
License: General Upload"""
        form_values.update(values)
        return {
            'media': media,
            'form': form,
            'form_values': form_values,
            'album_art_form_errors': album_art_form_errors,
            'album_art_form': AlbumArtForm(action=helpers.url_for(action='save_album_art', id=media.id)),
        }

    @expose()
    @validate(MediaForm(), error_handler=edit)
    def save(self, id, **values):
        media = self._fetch_media(id)
        if values.has_key('delete'):
            media.status.add('trash')
            DBSession.add(media)
            DBSession.flush()
            redirect(helpers.url_for(action='index'))

        if media.id == 'new':
            media.id = None

        media.slug = values['slug']
        media.title = values['title']
        media.author = Author(values['author_name'], values['author_email'])
        media.description = values['description']
        media.notes = values['notes']
        media.duration = helpers.duration_to_seconds(values['details']['duration'])
        media.set_tags(values['tags'])

        # parse url
#        url = urlparse(values['details']['url'], 'http')
#        if 'youtube.com' in url[1]:
#            if 'youtube.com/watch' in url[1]:
#                youtube_id = parse_qs(url[4])['v']
#                media.url = urlunparse(('http', 'youtube.com', '/v/%s' % youtube_id, '', None, None))
#            else:
#                media.url = values['details']['url']
#        else:
#            media.encode_url = values['details']['url']

        DBSession.add(media)
        DBSession.flush()
        redirect(helpers.url_for(action='edit', id=media.id))

    @expose()
    @validate(AlbumArtForm(), error_handler=edit)
    def save_album_art(self, id, **values):
        media = self._fetch_media(id)
        temp_file = values['album_art'].file
        im_path = '%s/../public/images/media/%d%%s.jpg' % (os.path.dirname(__file__), media.id)
        im = Image.open(temp_file)
        im.resize((162, 113), 1).save(im_path % 's')
        im.resize((240, 168), 1).save(im_path % 'm')
        redirect(helpers.url_for(action='edit', id=media.id))

    @expose('mediaplex.templates.admin.media.update-status-form')
    def update_status(self, id, update_button, **values):
        media = self._fetch_media(id)
        error = None

        if update_button == 'Review Complete':
            media.status.discard('unreviewed')

        elif update_button == 'Encoding Complete':
            original = [f for f in media.files if f.is_original][0]

            if original.type == media.ENCODED_TYPE:
                media.status.discard('unencoded') # dumb data -- already encoded
            else:
                orig_name, orig_ext = os.path.splitext(original.url)
                encoded_url = '%s.%s' % (orig_name, media.ENCODED_TYPE)
                encoded_path = os.path.join(config.media_dir, encoded_url)
                if os.path.exists(encoded_path):
                    encoded_file = MediaFile()
                    encoded_file.type = media.ENCODED_TYPE
                    encoded_file.url = encoded_url
                    encoded_file.size = os.stat(encoded_path)[6]
                    media.files.append(encoded_file)
                    media.status.discard('unencoded')
                else:
                    error = u'Encoded media not found, please upload and name it: %s' % encoded_url

        elif update_button == 'Publish Now':
            media.status.discard('draft')
            media.status.add('publish')
            media.publish_on = datetime.now()

        else:
            error = u'No action to perform'

        return dict(media=media, status_error=error)

    def _fetch_media(self, id):
        if id == 'new':
            media = Media()
            media.id = 'new'
        else:
            media = DBSession.query(Media).get(id)
        return media