git status --porcelain | while read status file; do
    if [[ $status == M* ]]; then
        msg="modify $file"
    elif [[ $status == ?? ]]; then
        msg="add $file"
    else
        msg="update $file"
    fi

    git add "$file"
    git commit -m "$msg"
done
