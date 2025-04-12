#!/usr/bin/python3

# imports
import sqlalchemy
import os
import datetime
import zipfile
import io
import json

################################################################################
# helper functions
################################################################################


def remove_nulls(s):
    r'''
    Postgres doesn't support strings with the null character \x00 in them, but twitter does.
    This helper function replaces the null characters with an escaped version so that they can be loaded into postgres.
    Technically, this means the data in postgres won't be an exact match of the data in twitter,
    and there is no way to get the original twitter data back from the data in postgres.

    The null character is extremely rarely used in real world text (approx. 1 in 1 billion tweets),
    and so this isn't too big of a deal.
    A more correct implementation, however, would be to *escape* the null characters rather than remove them.
    This isn't hard to do in python, but it is a bit of a pain to do with the JSON/COPY commands for the denormalized data.
    Since our goal is for the normalized/denormalized versions of the data to match exactly,
    we're not going to escape the strings for the normalized data.

    >>> remove_nulls('\x00')
    ''
    >>> remove_nulls('hello\x00 world')
    'hello world'
    '''
    if s is None:
        return None
    else:
        return s.replace('\x00','')


def get_id_urls(url, connection):
    '''
    Given a url, return the corresponding id in the urls table.
    If no row exists for the url, then one is inserted automatically.

    NOTE:
    This function cannot be tested with standard python testing tools because it interacts with the db.
    '''
    sql = sqlalchemy.sql.text('''
    insert into urls 
        (url)
        values
        (:url)
    on conflict do nothing
    returning id_urls
    ;
    ''')
    res = connection.execute(sql,{'url':url}).first()

    # when no conflict occurs, then the query above inserts a new row in the url table and returns id_urls in res[0];
    # when a conflict occurs, then the query above does not insert or return anything;
    # we need to run a select statement to put the already existing id_urls into res[0]
    if res is None:
        sql = sqlalchemy.sql.text('''
        select id_urls 
        from urls
        where
            url=:url
        ''')
        res = connection.execute(sql,{'url':url}).first()

    id_urls = res[0]
    return id_urls


def insert_tweet(connection,tweet):
    '''
    Insert the tweet into the database.

    Args:
        connection: a sqlalchemy connection to the postgresql db
        tweet: a dictionary representing the json tweet object

    NOTE:
    This function cannot be tested with standard python testing tools because it interacts with the db.
    
    FIXME:
    This function is only partially implemented.
    You'll need to add appropriate SQL insert statements to get it to work.
    '''

    # skip tweet if it's already inserted
    sql=sqlalchemy.sql.text('''
    SELECT id_tweets 
    FROM tweets
    WHERE id_tweets = :id_tweets
    ''')
    res = connection.execute(sql,{
        'id_tweets':tweet['id'],
        })
    if res.first() is not None:
        return

    # insert tweet within a transaction;
    # this ensures that a tweet does not get "partially" loaded
    with connection.begin() as trans:

        ########################################
        # insert into the users table
        ########################################
        if tweet['user']['url'] is None:
            user_id_urls = None
        else:
            user_id_urls = get_id_urls(tweet['user']['url'], connection)

        # create/update the user
         sql = sqlalchemy.sql.text('''
         INSERT INTO users
                (    id_users
                ,    created_at
                ,    updated_at
                ,    id_urls
                ,    friends_count
                ,    listed_count
                ,    favourites_count
                ,    statuses_count
                ,    protected
                ,    verified
                ,    screen_name
                ,    name
                ,    location
                ,    description
                ,    withheld_in_countries
                )
                VALUES
                (   :id_users
                ,   :created_at
                ,   :updated_at
                ,   :id_urls
                ,   :friends_count
                ,   :listed_count
                ,   :favourites_count
                ,   :statuses_count
                ,   :protected
                ,   :verified
                ,   :screen_name
                ,   :name
                ,   :location
                ,   :description
                ,   :withheld_in_countries
                )
                ON CONFLICT DO NOTHING
                ''')
        res = connection.execute(sql,{
            'id_users':tweet['user']['id'],
            'created_at':remove_nulls(tweet['created_at']),
            'updated_at':datetime.datetime.now(),
            'id_urls':user_id_urls,
            'friends_count':tweet['user']['friends_count'],
            'listed_count':tweet['user']['listed_count'],
            'favourites_count':tweet['user']['favourites_count'],
            'statuses_count':tweet['user']['statuses_count'],
            'protected':tweet['user']['protected'],
            'verified':tweet['user']['verified'],
            'screen_name':remove_nulls(tweet['user']['screen_name']),
            'name':remove_nulls(tweet['user']['name']),
            'location':remove_nulls(tweet['user']['location']),
            'description':remove_nulls(tweet['user']['description']),
            'withheld_in_countries':remove_nulls(tweet['user']['withheld_in_countries']) if 'withheld_in_countries' in tweet['user'] else None
            })

        ########################################
        # insert into the tweets table
    ########################################

        try:
            geo_coords = tweet['geo']['coordinates']
            geo_coords = str(tweet['geo']['coordinates'][0]) + ' ' + str(tweet['geo']['coordinates'][1])
            geo_str = 'POINT'
        except TypeError:
            try:
                geo_coords = '('
                for i,poly in enumerate(tweet['place']['bounding_box']['coordinates']):
                    if i>0:
                        geo_coords+=','
                    geo_coords+='('
                    for j,point in enumerate(poly):
                        geo_coords+= str(point[0]) + ' ' + str(point[1]) + ','
                    geo_coords+= str(poly[0][0]) + ' ' + str(poly[0][1])
                    geo_coords+=')'
                geo_coords+=')'
                geo_str = 'MULTIPOLYGON'
            except KeyError:
                if tweet['user']['geo_enabled']:
                    geo_str = None
                    geo_coords = None

        try:
            text = clean(tweet['extended_tweet']['full_text'])
        except:
            text = clean(tweet['text'])

        try:
            country_code = tweet['place']['country_code'].lower()
        except TypeError:
            country_code = None

        if country_code == 'us':
            state_code = tweet['place']['full_name'].split(',')[-1].strip().lower()
            if len(state_code)>2:
                state_code = None
        else:
            state_code = None

        try:
            place_name = tweet['place']['full_name']
        except TypeError:
            place_name = None

        # NOTE:
        # The tweets table has the following foreign key:
        # > FOREIGN KEY (in_reply_to_user_id) REFERENCES users(id_users)
        #
        # This means that every "in_reply_to_user_id" field must reference a valid entry in the users table.
        # If the id is not in the users table, then you'll need to add it in an "unhydrated" form.
        if tweet.get('in_reply_to_user_id',None) is not None:
            sql=sqlalchemy.sql.text('''
            SELECT 
            FROM users
            ''')

        # insert the tweet
        sql = sqlalchemy.sql.text('''
            INSERT INTO users
                (    id_users
                ,    created_at
                ,    updated_at
                ,    id_urls
                ,    friends_count
                ,    listed_count
                ,    favourites_count
                ,    statuses_count
                ,    protected
                ,    verified
                ,    screen_name
                ,    name
                ,    location
                ,    description
                ,    withheld_in_countries
                )
            VALUES
                (   :id_users
                ,   :created_at
                ,   :updated_at
                ,   :id_urls
                ,   :friends_count
                ,   :listed_count
                ,   :favourites_count
                ,   :statuses_count
                ,   :protected
                ,   :verified
                ,   :screen_name
                ,   :name
                ,   :location
                ,   :description
                ,   :withheld_in_countries
                )
                ON CONFLICT DO NOTHING
                ''')
        res = connection.execute(sql,{
            'id_users':tweet['user']['id'],
            'created_at':remove_nulls(tweet['created_at']),
            'updated_at':datetime.datetime.now(),
            'id_urls':user_id_urls,
            'friends_count':tweet['user']['friends_count'],
            'listed_count':tweet['user']['listed_count'],
            'favourites_count':tweet['user']['favourites_count'],
            'statuses_count':tweet['user']['statuses_count'],
            'protected':tweet['user']['protected'],
            'verified':tweet['user']['verified'],
            'screen_name':remove_nulls(tweet['user']['screen_name']),
            'name':remove_nulls(tweet['user']['name']),
            'location':remove_nulls(tweet['user']['location']),
            'description':remove_nulls(tweet['user']['description']),
            'withheld_in_countries':remove_nulls(tweet['user']['withheld_in_countries']) if 'withheld_in_countries' in tweet['user'] else None
            })

        ########################################
        # insert into the tweet_urls table
        ########################################

        try:
            urls = tweet['extended_tweet']['entities']['urls']
        except KeyError:
            urls = tweet['entities']['urls']

        for url in urls:
            id_urls = get_id_urls(url['expanded_url'], connection)

            sql=sqlalchemy.sql.text('''
               SELECT entities 
               FROM tweets
               WHERE 
                                    ''')

        ########################################
        # insert into the tweet_mentions table
        ########################################

        try:
            mentions = tweet['extended_tweet']['entities']['user_mentions']
        except KeyError:
            mentions = tweet['entities']['user_mentions']

            place_name = None

        # NOTE:
        # The tweets table has the following foreign key:
        # > FOREIGN KEY (in_reply_to_user_id) REFERENCES users(id_users)
        #
        # This means that every "in_reply_to_user_id" field must reference a valid entry in the users table.
        # If the id is not in the users table, then you'll need to add it in an "unhydrated" form.
        if tweet.get('in_reply_to_user_id',None) is not None:
            sql=sqlalchemy.sql.text('''
            INSERT INTO users (id_users)
            VALUES (:in_reply_to_user_id)
            ON CONFLICT DO NOTHING
            ''')

            connection.exectue(sql, {'in_reply_to_user_id': tweet['in_reply_to_user_id']})

        # insert the tweet
        sql=sqlalchemy.sql.text(f'''
            INSERT INTO TWEETS(
                id_tweets,
                id_users,
                created_at, 
                in_reply_to_status_id,
                in_reply_to_user_id,
                quoted_status_id,
                retweet_count,
                favorite_count,
                quote_count, 
                withheld_copyright,
                withheld_in_countries, 
                source, 
                text,
                country_code,
                state_code, 
                lang, 
                place_name, 
                geo
        )
            VALUES(
                :id_tweets,
                :id_users,
                :created_at,
                :in_reply_to_status_id,
                :in_reply_to_user_id,
                :quoted_status_id,
                :retweet_count,
                :favorite_count,
                :quote_count,
                :withheld_copyright,
                :withheld_in_countries,
                :source,
                :text,
                :country_code,
                :state_code,
                :lang,
                :place_name,
                :geo
            )
            ON CONFLICT DO NOTHING
                                ''')
        res = connection.execute(sql, {
              'id_tweets' : tweet['id'], 
              'id_users' : tweet['user']['id'], 
              'created_at' : tweet['created_at'],
              'in_reply_to_status_id' : tweet.get('in_reply_to_status_id'), 
              'in_reply_to_user_id' : tweet.get('in_reply_to_user_id'), 
              'quoted_status_id' : tweet.get('quoted_status_id', None), 
              'retweet_count' : tweet['retweet_count'], 
              'favorite_count' : tweet['favorite_count'],
              'quote_count' : tweet.get('quote_count', None), 
              'withheld_copyright': tweet.get('withheld_copyright', False), 
              'withheld_in_countries' : tweet.get('withheld_in_cou    ntries', []), 
              'source' : tweet.get('source'), 
              'text' : text, 
              'country_code' : country_code, 
              'state_code' : state_code, 
              'lang' : tweet['lang'], 
              'place_name' : place_name, 
              'geo' : None
        }
        )

        ########################################
        # insert into the tweet_urls table
        ########################################

