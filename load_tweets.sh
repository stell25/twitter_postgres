#!/bin/sh

# list all of the files that will be loaded into the database
# for the first part of this assignment, we will only load a small test zip file with ~10000 tweets
# but we will write are code so that we can easily load an arbitrary number of files
files='
test-data.zip
'

echo 'load normalized'
for file in $files; do
    python3 load_tweets.py --db postgresql://postgres:pass@localhost:55555/postgres --inputs "$file" --print_every 10000
done

echo 'load denormalized'
for file in $files; do
    cat "$file" | sed 's/\\u0000//g' | psql postgresql://postgres:pass@localhost:55556 -c "COPY tweets_jsonb (data) FROM STDIN csv quote e'\x01' delimiter e'\x02';"
done

#2) by using denormalized representation, we have no guarantees on data integrity (UNIQUENESS) and so it is very easy to add the same tweet twice
#after you get denormalized working, comment (lines 15-18) it out so that you don't add too much data
#breaking your text cases
