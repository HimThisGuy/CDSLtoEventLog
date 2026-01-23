import pandas as pd
from pm4py.objects.log.obj import EventLog, Trace, Event, XESExtension
from pm4py.objects.log.exporter.xes import exporter as xes_exporter
import os
import warnings

pd.options.mode.copy_on_write = True

# Suppress DtypeWarning, No problem for this code
warnings.filterwarnings('ignore', category=pd.errors.DtypeWarning)

VITALS_COMPRESSION = True
LABS_COMPRESSION = True
DAY_SHIFT_H_THRESHOLD = 2
TIMEZONE = None

VALIDATE_TRACES = False
FILTER_TRACES = False

SRC = "../dataset/cdsl_db"
XES_DEST = "cdsl_log.xes"
CSV_DEST = "cdsl_log.csv"

patients = pd.read_csv(os.path.join(SRC,"patient_01.csv"), index_col = "patient_id", encoding='latin1')
diag_er = pd.read_csv(os.path.join(SRC,"diagnosis_er_02.csv"), index_col = "patient_id", encoding='latin1')
diag_h = pd.read_csv(os.path.join(SRC,"diagnosis_hosp_03.csv"), index_col = "patient_id", encoding='latin1')
vitals = pd.read_csv(os.path.join(SRC,"vital_signs_04.csv"), index_col = "vital_sign_id", encoding='latin1')
meds = pd.read_csv(os.path.join(SRC,"medication_05.csv"), index_col = "medication_id", encoding='latin1')
labs = pd.read_csv(os.path.join(SRC,"lab_06.csv"), index_col = "lab_id", encoding='latin1')

# Getting data only for first N cases for testing
# patients = patients.head(10)
# diag_er = diag_er[diag_er.index.isin(patients.index)]
# diag_h = diag_h[diag_h.index.isin(patients.index)]
# vitals = vitals[ vitals["patient_id"].isin(patients.index)]
# meds = meds[ meds["patient_id"].isin(patients.index)]
# labs = labs[ labs["patient_id"].isin(patients.index)]

print("Table loaded")

# Compress vitals table (LOSSY)
if VITALS_COMPRESSION:
    vitals = vitals.groupby(["patient_id","constants_ing_date","constants_ing_time"], as_index=False).last()

# Compress labs table (LOSSY)
if LABS_COMPRESSION:
    labs = labs.groupby(["patient_id","lab_number","lab_date","time_lab","item_lab"], as_index=False).last()

print("Compression Done")

def empty_to_nan(df):
    return df.map(lambda x : x if x != 0 and str(x).strip() != "" else float("nan"))

patients = empty_to_nan(patients)
vitals = empty_to_nan(vitals)
print("Cleanup Done")

# Join date and time in a timestamp column named <tg>
def join_date_time(df, date, time, tg = "timestamp"):
    df[tg] = pd.to_datetime(df[date] + " " + df[time], format="mixed")
    return df

# Swap two sets of columns in place, if <mask> is specified only swap where mask is True
def swap_in_place(df, col1, col2, mask = None):
    if mask is not None:
        df.loc[mask, [*col1, *col2]] = df.loc[mask, [*col2, *col1]].values
    else:
        df[[*col1, *col2]] = df[[*col2, *col1]].values

# Simple join for vitals, labs, and ER Admission
join_date_time(vitals,"constants_ing_date","constants_ing_time")
join_date_time(labs,"lab_date","time_lab")
join_date_time(patients,"admission_date_emerg","time_admission_emerg",tg = "er_adm")

# ICU events are already in right format
patients["icu_date_in"] = pd.to_datetime(patients["icu_date_in"], format = "mixed")
patients["icu_date_out"] = pd.to_datetime(patients["icu_date_out"], format = "mixed")

# ER Triage and last visits timestamp calculation
join_date_time(patients,"admission_date_emerg","time_constant_first_emerg",tg = "er_triage")
join_date_time(patients,"admission_d_inpat","time_constant_last_emerg",tg = "er_last")

# Shift ER Triage date when day changes and result first
shift_mask = (patients["er_triage"] < patients["er_adm"]) & (patients["er_triage"].dt.hour <= DAY_SHIFT_H_THRESHOLD)
patients.loc[shift_mask, "er_triage"] += pd.Timedelta(days=1)

# Swap if triage is after er last visit or triage doesn't exist
er_tri_attr = ["er_triage","bp_max_first_emerg", "bp_min_first_emerg", "temp_first_emerg", "hr_first_emerg", "sat_02_first_emerg","glu_first_emerg"]
er_last_attr = ["er_last","bp_max_last_emerg", "bp_min_last_emerg", "temp_last_emerg", "hr_last_emerg", "sat_02_last_emerg","glu_last_emerg"]
last_after_try_mask = pd.isna(patients["er_triage"]) | (patients["er_triage"] > patients["er_last"])
swap_in_place(patients, er_tri_attr, er_last_attr, last_after_try_mask)

# ER Discharge
# Gettin timestamp of last labs visit made in er
er_lab = labs[labs["lab_number"].str.startswith("U")]
last_er_lab = er_lab.groupby("patient_id")["timestamp"].max()

# Selecting greater between last er check and last er lab
# Setting Baseline
patients["er_dis"] = patients["er_last"]
patients.loc[patients["er_dis"].isna(), "er_dis"] = patients.loc[patients["er_dis"].isna(),"er_triage"] + pd.Timedelta(seconds = 1)

# Selecting best between ER Last visit and Last ER lab when both are present
mask = pd.notna(patients["er_dis"]) & patients.index.isin(last_er_lab.index)
to_update = patients.loc[mask, "er_dis"]
patients.loc[mask, "er_dis"] = to_update.combine(last_er_lab.loc[to_update.index], lambda a, b: a if a > b else b) # Pick max
# Offset by 1s to make sure is after reference event
patients.loc[pd.notna(patients["er_dis"]),"er_dis"] += pd.Timedelta(seconds = 1)

# Hospital admission date (After Ed discharge or filled on 00:00 on missing Ed)
patients["hosp_adm"] = patients["er_dis"] + pd.Timedelta(seconds = 1)
patients.loc[pd.isna(patients["er_dis"]),["hosp_adm"]] = pd.to_datetime(patients["admission_d_inpat"])

# Converting DateTime attribute
meds["drug_end_date"] = pd.to_datetime(meds["drug_end_date"], format="mixed")
patients["ant_admission_date_in"] = pd.to_datetime(patients["ant_admission_date_in"], format="mixed")

if(TIMEZONE):
    meds["drug_end_date"] = meds["drug_end_date"].dt.tz_localize(TIMEZONE)
    patients["ant_admission_date_in"] = patients["ant_admission_date_in"].dt.tz_localize(TIMEZONE)

print("Prepared Timestamp")

# Creating inference table, used to deduce unknown time of some events
# Extracting timestamps of events with known time
vitals_timestap = vitals[["patient_id","timestamp"]]
labs_timestamp = labs[["patient_id","timestamp"]]
icu_timestamp = patients[["icu_date_out"]].reset_index().rename(columns = {"icu_date_out":"timestamp"})
h_adm_timestamp = patients[["hosp_adm"]].reset_index().rename(columns = {"hosp_adm":"timestamp"})
er_try_timestamp = patients[["er_triage"]].reset_index().rename(columns = {"er_triage":"timestamp"})

# Selecting canditate to first and last events
early_candidates = [h_adm_timestamp, er_try_timestamp]
late_candidates = [h_adm_timestamp, icu_timestamp, vitals_timestap, labs_timestamp]

early_candidates = pd.concat(early_candidates, ignore_index=True)
late_canditates = pd.concat(late_candidates, ignore_index=True)

# Extract per case eary and late event
early_indexes = early_candidates.groupby("patient_id")["timestamp"].idxmin()
early = early_candidates.loc[early_indexes]
early.rename(columns = {"timestamp":"early_time"}, inplace = True)

late_indexes = late_canditates.groupby("patient_id")["timestamp"].idxmax()
late = late_canditates.loc[late_indexes]
late.rename(columns = {"timestamp":"late_time"}, inplace = True)

inference_t = early.merge(late, on = "patient_id")
inference_t.set_index("patient_id", inplace = True)

print("Timestamp table created")


# Function declarations used in extraction
# infer time based on a inference table based on specified rule
def infer_time(el_id, date, mode, inf_table, force_date = False):

    date = pd.to_datetime(date)
    # Select reference timestamp from the table based on the mode
    match(mode):
        case "NOT_FIRST" | "FIRST":
            ref_time = inf_table.loc[el_id, "early_time"]
        case "LAST":
            ref_time = inf_table.loc[el_id, "late_time"]

    if pd.isna(ref_time):
        return date

    # Wrong day isn't changed because either doesn't matter or is sure that is wrong
    if ref_time.date() != date.date() and not force_date:
        return date

    # Shift after first
    if mode == "NOT_FIRST":
        if date > ref_time:
            return date

        # Offsetting time of 1s to make sure is after
        return ref_time + pd.Timedelta(seconds = 1)

    # Shift before first
    if mode == "FIRST":
        if date < ref_time:
            return date

        # Updating first element time in case of more "FIRST"
        inf_table.loc[el_id, "early_time"] = ref_time - pd.Timedelta(seconds = 1)
        return ref_time - pd.Timedelta(seconds = 1)

    # Shift after last
    if mode == "LAST":
        if date > ref_time:
            return date

        # Updating last element time in case of more "LAST"
        inf_table.loc[el_id, "late_time" ] = ref_time + pd.Timedelta(seconds = 1)
        return ref_time + pd.Timedelta(seconds = 1)

# Create function to estract event from table
def event_collector_factory(table, case_col, name, time_col, infer_mode = None, infer_table = None, attr = {}):
    # Add time_col to attribute with name timestamp
    attr = {time_col:"timestamp", **attr}

    def get_events(case_id):
        # Extract events rows in table, case_col = None means is the index
        if(case_col):
            tg_rows = table[table[case_col] == case_id]
        else:
            tg_rows = table.loc[[case_id]]

        # Filter rows with empty time column
        tg_rows = tg_rows[ pd.notna(tg_rows[time_col])]
        if tg_rows.empty:
            return None

        # Filter and Rename columns with attribute name
        event = tg_rows[[*attr.keys()]]
        event.rename(columns = attr, inplace=True)
        event["activity"] = name

        # Infer time if specified
        if ( infer_mode != None ):
            event["timestamp"] = event["timestamp"].map(lambda t : infer_time(case_id, t, infer_mode, infer_table))

        return event

    return get_events

# Create function to estract event from multiple table by joinining them
def event_joined_collector(tables, case_col, name, time_col, join_on = None,
    infer_mode = None, infer_table = None, attr = {}):

    # Extracting first table and the rest
    table = tables[0]
    tables = tables[1:]

    # joining tables
    if(join_on):
        table = table.merge(tables, on = join_on, how = "outer")
    else:
        table = table.join(tables, how = "outer")

    return event_collector_factory(table, case_col, name, time_col, infer_mode, infer_table, attr)

# Create a function that extract events and group them by timestamp and eventual other attribute
# if no attribute is passed automatically adds a count attribute to the events
def grouper_collector_factory(table, case_col, name, time_col, infer_mode = None, infer_table = None,
    attr = {}, group_attr = {}):

    all_attr = {time_col:"timestamp",**attr,**group_attr}
    group_attr = {time_col:"timestamp",**group_attr}

    def get_events(case_id):

        # Event rows in table, case_col = None means is the index
        if(case_col):
            tg_rows = table[table[case_col] == case_id]
        else:
            tg_rows = table.loc[[case_id]]

        # Filter rows with empty time column
        tg_rows = tg_rows[ pd.notna(tg_rows[time_col])]
        if tg_rows.empty:
            return None

        # Preparing all attribute
        events = tg_rows[all_attr.keys()]
        events.rename(columns = all_attr, inplace=True)

        # Group events using attribute if passed, or counting grouped events
        if attr:
            events["row"] = events.groupby([*group_attr.values()]).cumcount()       # Count for col name
            events = events.pivot(index = [*group_attr.values()], columns = "row")  # Pivot around group attr
            events.columns = [f"{col}_{i}" for col, i in events.columns]            # Setting column name
            events.reset_index(inplace = True)
        else:
            events = events.groupby([*group_attr.values()], as_index = False).size()
            events.rename(columns = {"size":"count"}, inplace = True)

        events["activity"] = name

        # Infer time if specified
        if ( infer_mode != None ):
            events["timestamp"] = events["timestamp"].map(lambda t : infer_time(case_id, t, infer_mode, infer_table))

        return events

    return get_events


# Create a map of attributes for a given origin and name that have a suffix of _<i>
def attr_map_for(origin, name, start = 1, end = 1, pad_zeros = 0):

    fstring_origin = "{o}_{i:0" + str(pad_zeros) + "d}"
    fstring_name = "{n}_{i:0" + str(pad_zeros) + "d}"

    return {
        fstring_origin.format(o = origin, i = i): 
        fstring_name.format(n = name, i = i) 
        for i in range(start, end + 1)
    }

# Create a function that extract trace attributes from a table
def trace_attributes_collector_factory(table, case_col, attr = {}):
    attr = { key: f"case:{val}" for key, val in attr.items()}
    
    def get_trace_attributes(case_id):
        # Get the event row in the table, case_col = None means is the index, Expected one
        if(case_col):
            tg_row = table[table[case_col] == case_id].iloc[0]
        else:
            tg_row = table.loc[case_id]

        # Filter and Rename columns with attribute name
        trace_attr = tg_row[attr.keys()]
        trace_attr.rename(attr, inplace=True)

        return trace_attr

    return get_trace_attributes

# Define events collectors
collectors = []
collectors.append(
    event_collector_factory(patients,None,"ER Admission","er_adm",
    attr = {
        "diag_emerg":"er_admission_diagnosis",
        "department_emerg":"department"
    })
)
collectors.append(
    event_collector_factory(patients,None,"ER Triage","er_triage",
    attr = {
        "bp_max_first_emerg":"blood_press_max",
        "bp_min_first_emerg":"blood_press_min",
        "temp_first_emerg":"temp",
        "hr_first_emerg":"heart_rate",
        "sat_02_first_emerg":"O2_saturation",
        "glu_first_emerg":"glucose"
    })
)
collectors.append(
    event_collector_factory(patients,None,"ER Last visit","er_last",
    attr = {
        "bp_max_last_emerg":"blood_press_max",
        "bp_min_last_emerg":"blood_press_min",
        "temp_last_emerg":"temp",
        "hr_last_emerg":"heart_rate",
        "sat_02_last_emerg":"O2_saturation",
        "glu_last_emerg":"glucose",
    })
)
collectors.append(
    event_joined_collector([patients,diag_er],None,"ER Discharge","er_dis",
    attr = {
        "destin_emerg":"er_destination",
        "dia_ppal":"principal_diagnosis",
        **attr_map_for("dia","diagnosis",start = 2, end = 12, pad_zeros = 2),
        **attr_map_for("proc","procedure",start = 1, end = 5, pad_zeros = 2)
    })
)
collectors.append(
    event_collector_factory(patients,None,"Hospital Admission","hosp_adm",
    attr = {
        "diag_inpat":"hosp_admission_diagnosis",
    })
)
collectors.append( event_collector_factory(patients,None,"ICU stay","icu_date_in"))
collectors.append( event_collector_factory(patients,None,"ICU Discharge","icu_date_out") )
collectors.append(
    event_collector_factory(vitals,"patient_id","Check Vitals","timestamp",
    attr = {
        "bp_max_ing":"blood_press_max",
        "bp_min_ing":"blood_press_min",
        "temp_ing":"temp",
        "hr_ing":"heart_rate",
        "sat_02_ing":"O2_saturation",
        "glu_ing":"glucose",
    })
)
collectors.append(
    grouper_collector_factory(meds,"patient_id","Medication","drug_start_date",
    attr = {
        "daily_avrg_dose":"daily_dose",
        "drug_comercial_name":"drug_name",
        "id_atc5":"id_atc5",
        "id_atc7":"id_atc7",
        "drug_end_date":"drug_end"
    },
    infer_mode = "NOT_FIRST", infer_table = inference_t)
)
collectors.append(
    grouper_collector_factory(labs,"patient_id","Lab Test","timestamp",
    attr = {
        "item_lab":"item",
        "val_result":"res_value",
        "result_text":"res_text",
        "ud_result":"measurement_unit",
        "ref_values":"ref_values"
    },
    group_attr = {
        "lab_number":"lab_number"
    },
    infer_mode = "NOT_FIRST", infer_table = inference_t)
)
collectors.append(
    event_joined_collector([patients, diag_h],None,"Hospital Discharge","discharge_date",
    attr = {
        "destin_discharge":"hosp_destination",
        "dia_ppal":"principal_diagnosis",
        "poad_ppal":"principal_diagnosis_poa",
        **attr_map_for("dia","diagnosis",start = 2, end = 19, pad_zeros = 2),
        **attr_map_for("poad","diagnosis_poa",start = 2, end = 19, pad_zeros = 2),
        **attr_map_for("proc","procedure",start = 1, end = 20, pad_zeros = 2)
    },
    infer_mode = "LAST", infer_table = inference_t)
)

trace_attr_col = trace_attributes_collector_factory(patients, None,
attr = {
    "sex":"sex",
    "age":"age",
    "ant_admission_date_in":"previous_admission_date",
    "ant_diag_inpat":"previous_diagnosis"
})

# Build traces for patients using the list of event collectors
traces = {}     # Collect all generated traces

for i,case in enumerate(patients.index):
    # Get all event assiociated with the case_id <case>
    events = []
    for collector in collectors:
        e = collector(case)
        if e is not None:
            events.append(e)

    # Building and sorting trace by time
    trace = pd.concat(events, ignore_index=True).sort_values("timestamp")
    # Add trace attribute to each event
    trace["case_id"] = case
    trace_attr = trace_attr_col(case)
    trace[trace_attr.index] = trace_attr.values

    traces[case] = trace

    print(f"{i+1} : Done Case {case}")

events = 0
for trace in traces.values():
    events += trace.shape[0]

print("\nDone")
print(f" - Total traces : {traces.__len__()}")
print(f" - Total events : {events}")

# Utility class to represent a violation type
if(VALIDATE_TRACES or FILTER_TRACES):
    class Violation:
        def __init__(self, description):
            self.desc = description
            self.cases = set()
            self.count = 0

        def add_case(self, case):
            self.cases.add(case)
            self.count += 1

        def __str__(self):
            return f"In {self.count} cases {self.desc}"

        @staticmethod
        def print_all(violations):
            violations = filter(lambda v : v.count > 0, violations)
            count = 0
            cases = set()
            for i,v in enumerate(violations):
                print(i,"-",v)
                count += v.count
                cases.update(v.cases)
            print(f"\nTotal errors: {count}")
            print(f"Invalid cases: {cases.__len__()}")

        @staticmethod
        def get_cases(violations):
            cases = set()
            for v in violations:
                cases.update(v.cases)
            return cases

    # Functions to check for violations

    # Check if trace has event <name>
    def check_has(traces, name):
        err = Violation(f"{name} was not present")
        for case,trace in traces.items():
            if (trace["activity"] != name).all():
                err.add_case(case)
        return err

    # Check that first is event is <name>
    def check_first(traces, name):
        err_dict = {}
        for case,trace in traces.items():
            first = trace.iloc[0]["activity"]
            if first != name:
                if(err_dict.get(first)):
                    err_dict[first].add_case(case)
                else:
                    err_dict[first] = Violation(f"{first} was the first instead of {name}")
                    err_dict[first].add_case(case)
        return err_dict.values()

    # Check that last is event is <name>
    def check_last(traces, name):
        err_dict = {}
        for case,trace in traces.items():
            last = trace.iloc[-1]["activity"]
            if last != "Hospital Discharge":
                if(err_dict.get(last)):
                    err_dict[last].add_case(case)
                else:
                    err_dict[last] = Violation(f"{last} was last instead of {name}")
                    err_dict[last].add_case(case)
        return err_dict.values()

    # Check weather 2 activity are in sequence
    def check_sequence(traces, first, second):
        err = Violation(f"{second} was before {first}")
        for case,trace in traces.items():
            f_event = trace[ trace["activity"] == first ]
            s_event = trace[ trace["activity"] == second ]

            if(f_event.empty or s_event.empty):
                continue
            elif f_event.iloc[-1]["timestamp"] > s_event.iloc[0]["timestamp"]:
                err.add_case(case)
        return err

    # Splitting traces in segments for check for the right events
    # Traces with ER Visit
    er_traces = {}
    for case, trace in traces.items():
        if (trace["activity"] == "ER Admission").any():
            er_traces[case] = trace

    # Traces without ER Visit
    hosp_traces = {}
    for case, trace in traces.items():
        if (trace["activity"] != "ER Admission").all():
            hosp_traces[case] = trace

    # Traces with only ER Labs
    er_lab_traces = {}
    for case, trace in er_traces.items():
        if("number" in trace.columns):
            er_lab_traces[case] = trace[pd.isna(trace["number"]) | trace["number"].str.startswith("U")]

    print("Done")

    errors = []

    errors.extend(check_first(er_traces, "ER Admission"))
    errors.extend(check_first(hosp_traces, "Hospital Admission"))
    errors.extend(check_last(traces, "Hospital Discharge"))

    print("Endpoint Checked")

    errors.append(check_sequence(traces, "ER Admission", "ER Discharge"))
    errors.append(check_sequence(traces, "ER Admission", "Hospital Admission"))
    errors.append(check_sequence(traces, "ER Discharge", "Hospital Admission"))
    errors.append(check_sequence(traces, "Hospital Admission", "Hospital Discharge"))
    errors.append(check_sequence(er_lab_traces, "Lab Test", "ER Discharge"))

    print("Sequence Checked")

    errors.append(check_has(er_traces, "ER Triage"))
    errors.append(check_sequence(er_traces, "ER Triage", "ER Last visit"))
    errors.append(check_sequence(er_traces, "ER Admission", "ER Triage"))
    errors.append(check_sequence(er_traces, "ER Admission", "ER Last visit"))
    errors.append(check_sequence(er_traces, "ER Last visit", "ER Discharge"))
    errors.append(check_sequence(er_traces, "ER Triage", "ER Discharge"))

    print("ER Triage and Last visit Checked")

    print("\nReport")
    Violation.print_all(errors)

if(FILTER_TRACES):
    del_tot = Violation.get_cases(errors).__len__()
    for case in Violation.get_cases(errors):
        del traces[case]
    print(f"Deleted {del_tot} cases")

def move_columns(df, columns):
    other_cols = list(filter(lambda c: c not in columns,df.columns))
    return df[columns + other_cols]

if(CSV_DEST):
    traces_list = list(map(lambda x: x[1], traces.items()))
    log_df = pd.concat(traces_list, ignore_index=True)
    log_df = move_columns(log_df,["case_id", "activity", "timestamp"])
    print("Trace df concatenated")
    log_df.to_csv(CSV_DEST, index = False, date_format='%Y-%m-%d %H:%M:%S')
    print("Csv log saved at", CSV_DEST)

if(XES_DEST):
    # Prepare Traces for conversion
    missing_lifecycle = 0

    for trace in traces.values():
        if TIMEZONE:
            trace["timestamp"] = trace["timestamp"].dt.tz_localize(TIMEZONE)
        if( not trace.columns.str.contains("lifecycle").any() ):
            trace["lifecycle"] = "complete"
            missing_lifecycle += 1

        # Rename columns to standard names
        trace.rename(
            columns = {
                "activity":"concept:name",
                "timestamp":"time:timestamp",
                "lifecycle":"lifecycle:transition"
            },
            inplace = True
        )

    if missing_lifecycle != 0:
        print(f"WARNING: in {missing_lifecycle} traces no lifecycle column found, assuming all events are 'complete'")

    print("Done")

    # Create log object
    # Compile extention dict for event log
    def xes_extention_dict(*arg):
        exts = {}
        for ext in arg:
            exts[ext.name] = {"prefix" : ext.prefix, "uri": ext.uri}
        return exts

    # Empty event log
    event_log = EventLog(
        globals={
            "trace":{
                "concept:name": "case ID"
            },
            "event":{
                "concept:name": "activity",
                "time:timestamp": pd.Timestamp.now(),
                "lifecycle:transition": "lifecycle"
            }
        },
        attributes = { 
            "origin":"csv"
        },
        classifiers = {
            "concept:name": ["concept:name"]
        },
        extensions = xes_extention_dict(
            XESExtension.Concept,
            XESExtension.Time,
            XESExtension.Lifecycle
        ),
    )

    print("Done")

    # Creating a trace for each case_id, assumed event in order
    for case,t in traces.items():
        trace = Trace()
        trace.attributes['concept:name'] = case
        
        # Getting attributes name
        trace_attr = list(filter(lambda a : a.startswith("case:"), t.columns))
        event_attr = list(filter(lambda a : not a.startswith("case:"), t.columns))

        for attr in trace_attr:
            if pd.notna(t[attr].iloc[0]):
                trace.attributes[attr] = t[attr].iloc[0]

        # building events
        for _,e in t.iterrows():
            event = Event()

            #Adding attribute
            for attr in event_attr:
                if pd.notna(e[attr]):
                    event[attr] = e[attr]

            trace.append(event)
        event_log.append(trace)
        print(f"Case: {case} done")

    print("\nDone")

    # Exporting event log to XES file
    xes_exporter.apply(event_log, XES_DEST)