import streamlit as st
import sqlite3
import json
import os
from datetime import datetime, timedelta

# ---------------------------
# Database Setup and Helpers
# ---------------------------

DB_FILE = "schedules.db"

def init_db():
    """Initialize the database and create tables if they do not exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            semester TEXT,
            schedule TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_weekdays():
    """Return a list of weekday names."""
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def get_time_slots():
    """
    Return a list of time slot strings in 15‑minute increments,
    starting at 06:00 and ending at 21:45 (each slot represents a 15‑minute block).
    """
    slots = []
    current = datetime.strptime("06:00", "%H:%M")
    end = datetime.strptime("22:00", "%H:%M")
    while current < end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=15)
    return slots

def get_user(username):
    """Return the user record as a dict (or None if not found)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, semester, schedule FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if row:
        username, semester, schedule_json = row
        schedule = json.loads(schedule_json) if schedule_json else {day: [] for day in get_weekdays()}
        return {"username": username, "semester": semester, "schedule": schedule}
    return None

def create_user(username, semester):
    """Create a new user with an empty schedule."""
    schedule = { day: [] for day in get_weekdays() }
    schedule_json = json.dumps(schedule)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (username, semester, schedule) VALUES (?, ?, ?)",
                   (username, semester, schedule_json))
    conn.commit()
    conn.close()

def update_schedule(username, schedule):
    """Update the schedule for the given username."""
    schedule_json = json.dumps(schedule)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET schedule = ? WHERE username = ?", (schedule_json, username))
    conn.commit()
    conn.close()

def load_all_users():
    """Load all user records from the database as a dict."""
    data = {}
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, semester, schedule FROM users")
    rows = cursor.fetchall()
    conn.close()
    for row in rows:
        username, semester, schedule_json = row
        schedule = json.loads(schedule_json) if schedule_json else {day: [] for day in get_weekdays()}
        data[username] = {"semester": semester, "schedule": schedule}
    return data

# Predefined semester options up through Summer 2028.
semester_options = [
    "Summer 2025", "Fall 2025", "Spring 2026",
    "Summer 2026", "Fall 2026", "Spring 2027",
    "Summer 2027", "Fall 2027", "Spring 2028", "Summer 2028"
]

# ---------------------------
# User Login / Registration
# ---------------------------
def login():
    st.sidebar.title("User Login / Registration")
    username = st.sidebar.text_input("Enter your username:")
    if username:
        user = get_user(username)
        if user:
            st.sidebar.success(f"Logged in as **{username}** (Semester: {user['semester']})")
            st.session_state.current_user = username
        else:
            st.sidebar.info("New user detected. Please select your semester and create an account.")
            semester = st.sidebar.selectbox("Select your semester:", semester_options)
            if st.sidebar.button("Create Account"):
                create_user(username, semester)
                st.sidebar.success(f"Account created for **{username}** in **{semester}**.")
                st.session_state.current_user = username

# ---------------------------
# Schedule Editor with Hour Toggle
# ---------------------------
def schedule_editor():
    st.header("Edit Your Schedule")
    current_user = st.session_state.current_user
    user_record = get_user(current_user)
    schedule = user_record.get("schedule", { day: [] for day in get_weekdays() })
    
    st.write("For each day, click on the 15‑minute blocks during which you are **BUSY**. "
             "To mark or clear an entire hour, click the bold hour button at the left.")
    
    new_schedule = {}
    
    for day in get_weekdays():
        st.subheader(day)
        day_busy = []
        # Loop through each hour from 06:00 to 21:00.
        for hour in range(6, 22):
            cols = st.columns(5)
            toggle_key = f"{current_user}_{day}_toggle_{hour}"
            # When the toggle button is clicked, toggle the value for all blocks in this hour.
            if cols[0].button(f"**{hour:02d}:00**", key=toggle_key):
                # Build keys for the four 15‑minute blocks.
                block_keys = [f"{current_user}_{day}_{hour:02d}:{m}" for m in ["00", "15", "30", "45"]]
                all_checked = True
                for i, key in enumerate(block_keys):
                    time_str = f"{hour:02d}:{['00','15','30','45'][i]}"
                    default_val = time_str in schedule.get(day, [])
                    if key not in st.session_state:
                        st.session_state[key] = default_val
                    if not st.session_state[key]:
                        all_checked = False
                        break
                new_value = not all_checked
                for key in block_keys:
                    st.session_state[key] = new_value

            # Create checkboxes for the four 15‑minute blocks.
            for idx, minute in enumerate(["00", "15", "30", "45"]):
                time_str = f"{hour:02d}:{minute}"
                default_val = time_str in schedule.get(day, [])
                key = f"{current_user}_{day}_{time_str}"
                if key not in st.session_state:
                    st.session_state[key] = default_val
                # Do not pass the value= parameter; let the widget use st.session_state.
                if cols[idx+1].checkbox(time_str, key=key):
                    day_busy.append(time_str)
            st.write("")  # spacing between rows
        new_schedule[day] = day_busy

    if st.button("Save Schedule"):
        update_schedule(current_user, new_schedule)
        st.success("Schedule saved successfully!")

# ---------------------------
# Meeting Gap Finder Functions (15-Minute Resolution)
# ---------------------------
def find_common_free_slots(selected_users, duration_slots):
    """
    For each day, find contiguous free blocks (of duration_slots consecutive 15‑minute slots)
    where all selected users are free.
    
    Returns a dict mapping each day to a list of tuples:
        (start_time, end_time, total_duration_in_minutes)
    """
    data = load_all_users()
    time_slots = get_time_slots()
    weekdays = get_weekdays()
    common_free = { day: [] for day in weekdays }
    
    for day in weekdays:
        free_flags = []
        for ts in time_slots:
            free = True
            for user in selected_users:
                user_schedule = data[user]["schedule"]
                if ts in user_schedule.get(day, []):
                    free = False
                    break
            free_flags.append(free)
        
        i = 0
        while i < len(time_slots):
            if free_flags[i]:
                start_idx = i
                while i < len(time_slots) and free_flags[i]:
                    i += 1
                end_idx = i - 1
                segment_length = end_idx - start_idx + 1
                if segment_length >= duration_slots:
                    start_time = time_slots[start_idx]
                    end_time = time_slots[end_idx]
                    common_free[day].append((start_time, end_time, segment_length * 15))
            else:
                i += 1
    return common_free

def find_min_conflict_gap(selected_users, window_slots=4):
    """
    If no completely free gap is available, evaluate every possible one‑hour block (4 slots),
    counting 1 conflict per user if any slot in the block is busy.
    
    Returns a tuple:
      (best_intervals, min_conflict)
    where best_intervals is a list of tuples (day, start_time, end_time, conflict_count)
    and min_conflict is the minimum conflict count found.
    """
    data = load_all_users()
    time_slots = get_time_slots()
    weekdays = get_weekdays()
    best_intervals = []
    min_conflict = None

    for day in weekdays:
        for i in range(len(time_slots) - window_slots + 1):
            block = time_slots[i : i + window_slots]
            conflict_count = 0
            for user in selected_users:
                user_schedule = data[user]["schedule"]
                if any(slot in user_schedule.get(day, []) for slot in block):
                    conflict_count += 1
            if min_conflict is None or conflict_count < min_conflict:
                min_conflict = conflict_count
                best_intervals = [(day, block[0], block[-1], conflict_count)]
            elif conflict_count == min_conflict:
                best_intervals.append((day, block[0], block[-1], conflict_count))
    return best_intervals, min_conflict

# ---------------------------
# Compare Schedules Page
# ---------------------------
def compare_schedules():
    st.header("Compare Schedules")
    data = load_all_users()
    if not data:
        st.info("No schedules available. Please have some users create schedules first.")
        return

    # Group users by semester.
    users_by_semester = {}
    for user, info in data.items():
        semester = info["semester"]
        users_by_semester.setdefault(semester, []).append(user)
    
    st.subheader("Select users to include in the comparison:")
    selected_users = []
    for semester, users in users_by_semester.items():
        st.markdown(f"### {semester}")
        for user in users:
            if st.checkbox(user, value=True, key=f"{user}_compare"):
                selected_users.append(user)
    
    if not selected_users:
        st.error("Please select at least one user for the comparison.")
        return

    if st.button("Find Common Gaps"):
        st.subheader("Time gaps where all selected users are free:")
        # Find gaps for 30 minutes (2 slots) and 1 hour (4 slots).
        common_free_30 = find_common_free_slots(selected_users, duration_slots=2)
        common_free_60 = find_common_free_slots(selected_users, duration_slots=4)
        
        found_any = False
        for day in get_weekdays():
            st.markdown(f"**{day}**")
            if common_free_30[day]:
                st.write("**30‑minute (or longer) free blocks:**")
                for interval in common_free_30[day]:
                    start_time, end_time, duration = interval
                    st.write(f"- {start_time} to {end_time} ({duration} minutes free)")
                if common_free_60[day]:
                    st.write("**Also, these blocks allow for a 1‑hour meeting:**")
                    for interval in common_free_60[day]:
                        start_time, end_time, _ = interval
                        st.write(f"- {start_time} to {end_time}")
                found_any = True
            else:
                st.write("No common free gap found.")
            st.write("---")
        
        if not found_any:
            st.info("No time gap found where all selected users are completely free.")
            st.subheader("Best one‑hour block (with minimal conflicts):")
            best_intervals, min_conflict = find_min_conflict_gap(selected_users, window_slots=4)
            st.write(f"Minimum conflict count: {min_conflict} user(s) busy.")
            for interval in best_intervals:
                day, start_time, end_time, conflict_count = interval
                st.write(f"- {day}: {start_time} to {end_time} ({conflict_count} conflict(s))")

# ---------------------------
# Main App
# ---------------------------
def main():
    st.title("Shared Schedule Gap Finder")
    # Initialize the database on startup.
    init_db()
    
    if "current_user" not in st.session_state:
        st.session_state.current_user = None

    # Show login/registration in the sidebar.
    login()

    if st.session_state.current_user:
        page = st.sidebar.radio("Navigation", ["Edit My Schedule", "Compare Schedules"])
        if page == "Edit My Schedule":
            st.subheader(f"Welcome, {st.session_state.current_user}!")
            schedule_editor()
        elif page == "Compare Schedules":
            compare_schedules()
    else:
        st.info("Please log in or create an account using the sidebar.")

if __name__ == '__main__':
    main()
