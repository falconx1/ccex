#!/usr/bin/env bash
# The statusline `ccex record --install` wires up when you don't already have one:
# model, context, cost, and the two usage windows as bars. Reads Claude Code's JSON
# payload on stdin. No jq -- grep and sed only, so it adds nothing to install.
input=$(cat)

jval() { echo "$input" | grep -o "\"$1\":[^,}]*" | head -1 | sed 's/.*://;s/^"//;s/"$//;s/^ *"//;s/" *$//'; }

model=$(jval display_name)
ctx=$(echo "$input" | grep -o '"used_percentage":[0-9]*' | head -1 | grep -o '[0-9]*$')
cost=$(echo "$input" | grep -o '"total_cost_usd":[0-9.]*' | head -1 | grep -o '[0-9.]*$')
five_h=$(echo "$input" | grep -o '"five_hour":{[^}]*}' | grep -o '"used_percentage":[0-9]*' | grep -o '[0-9]*$')
seven_d=$(echo "$input" | grep -o '"seven_day":{[^}]*}' | grep -o '"used_percentage":[0-9]*' | grep -o '[0-9]*$')

cost_fmt=""
[ -n "$cost" ] && cost_fmt=$(printf '%.2f' "$cost")

bar() {   # ten blocks, filled to the percentage
  local w=10 filled=$(( ${1:-0} * 10 / 100 ))
  local empty=$(( w - filled ))
  printf '\033[%sm' "$2"
  for ((i=0;i<filled;i++)); do printf '█'; done
  printf '\033[2m'
  for ((i=0;i<empty;i++)); do printf '░'; done
  printf '\033[00m'
}

bar_color() {
  local pct=${1:-0}
  if [ "$pct" -lt 50 ]; then echo "32"      # green
  elif [ "$pct" -lt 80 ]; then echo "33"    # yellow
  else echo "31"                            # red, and near where ccex rotate steps in
  fi
}

printf "\033[0;33m%s\033[00m" "${model:-Claude}"
[ -n "$ctx" ] && printf " \033[2m│\033[00m ctx:" && bar "$ctx" "$(bar_color "$ctx")" && printf " %s%%" "$ctx"
[ -n "$cost_fmt" ] && printf " \033[2m│\033[00m \$%s" "$cost_fmt"
[ -n "$five_h" ] && printf " \033[2m│\033[00m 5h:" && bar "$five_h" "$(bar_color "$five_h")" && printf " %s%%" "$five_h"
[ -n "$seven_d" ] && printf " \033[2m│\033[00m 7d:" && bar "$seven_d" "$(bar_color "$seven_d")" && printf " %s%%" "$seven_d"
