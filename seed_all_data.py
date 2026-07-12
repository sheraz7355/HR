"""
Comprehensive seed script for May 1, 2026 to July 12, 2026
Covers ALL modules: attendance, leaves, timesheets, compensation, pf,
digital_files, communications, loans, performance, workplace, projects,
holidays, policies, workflows, overtime, change_requests, kanban
"""
import sys, os, json, random, math
from datetime import date, datetime, timedelta, time
sys.path.insert(0, os.path.dirname(__file__))

from hr_app.app import create_app
from hr_app.extensions import db
from hr_app.models.user import User, Role, ChangeRequest
from hr_app.models.attendance import Attendance, AttendanceLog
from hr_app.models.holiday import BreakLog
from hr_app.models.leave import LeaveType, LeaveQuota, LeaveRequest, LeaveApproval
from hr_app.models.timesheet import TimesheetWeek, TimesheetEntry, TimesheetApproval
from hr_app.models.compensation import PayrollProfile, PayrollComponent, PayrollRun, PayrollSlip, SalaryRevision
from hr_app.models.pf import ProvidentFundConfig, PFContribution, PFLedger, PFWithdrawalRequest, PFLoanRequest
from hr_app.models.digital_file import FileCategory
from hr_app.models.communication import Notification, NotificationRecipient, EmailLog
from hr_app.models.digital_file import DigitalFile
from hr_app.models.loan import LoanAdvanceRequest, LoanRepayment
from hr_app.models.performance import PerformanceReview, PerformanceGoal
from hr_app.models.workplace import Announcement, TeamEvent, KanbanBoard, KanbanTask
from hr_app.models.project import Project, WorkPackage, ProjectTask
from hr_app.models.holiday import CompanyHoliday, TimePolicy, ApprovalWorkflow, OvertimeAccount, \
    AttendanceCorrection, ButtonPermission, PFProfitDistribution, PFSettlement, BreakLog
from hr_app.models.tax import IncomeTaxSlab

app = create_app()

random.seed(42)

def daterange(start, end):
    for n in range(int((end - start).days) + 1):
        yield start + timedelta(n)

def is_weekend(d):
    return d.weekday() >= 5

def random_clock():
    """Random clock time between 8:45 and 9:30"""
    base = 8 * 60 + 45
    offset = random.randint(0, 45)
    total = base + offset
    return time(total // 60, total % 60)

def random_clock_out(clock_in):
    """Clock out between 8-9.5 hours after clock in"""
    mins = random.randint(8 * 60, 9 * 60 + 30)
    ci = clock_in.hour * 60 + clock_in.minute
    co = ci + mins
    if co >= 24 * 60:
        co = 23 * 30
    return time(co // 60, co % 60)

app = create_app()

with app.app_context():
    db.create_all()

    # =====================================================================
    # USE EXISTING REFERENCE DATA
    # =====================================================================
    users = User.query.all()
    admin = User.query.filter_by(email='admin@solarkon.com').first()
    mgr = User.query.filter_by(email='manager@solarkon.com').first()
    employees = User.query.filter(User.role_id == 3).all()

    leave_types = LeaveType.query.all()
    lt_cl = LeaveType.query.filter_by(code='CL').first()
    lt_sl = LeaveType.query.filter_by(code='SL').first()
    lt_al = LeaveType.query.filter_by(code='AL').first()

    file_cats = FileCategory.query.all()

    pf_config = ProvidentFundConfig.query.first()
    if not pf_config:
        pf_config = ProvidentFundConfig(
            employee_contribution_pct=5.0, employer_contribution_pct=5.0,
            max_loan_percentage=50.0, interest_rate=0.0, min_service_months_for_loan=12
        )
        db.session.add(pf_config)

    # =====================================================================
    # DATE RANGE
    # =====================================================================
    start_date = date(2026, 5, 1)
    end_date = date(2026, 7, 12)
    all_dates = list(daterange(start_date, end_date))
    weekdays = [d for d in all_dates if not is_weekend(d)]

    print(f"Total days: {len(all_dates)}, weekdays: {len(weekdays)}")
    print(f"Period: {start_date} to {end_date}")

    # =====================================================================
    # 1. COMPANY HOLIDAYS
    # =====================================================================
    print("\n--- COMPANY HOLIDAYS ---")
    holidays_data = [
        ("Labour Day", date(2026, 5, 1), False),
        ("Eid-ul-Azha", date(2026, 5, 28), False),
        ("Independence Day", date(2026, 8, 14), True),
        ("Eid Milad-un-Nabi", date(2026, 9, 5), False),
        ("Pakistan Day", date(2026, 3, 23), True),
        ("Iqbal Day", date(2026, 11, 9), True),
        ("Quaid-e-Azam Day", date(2026, 12, 25), True),
        ("Summer Break", date(2026, 6, 15), False),
    ]
    for name, hdate, recurring in holidays_data:
        if not CompanyHoliday.query.filter_by(holiday_date=hdate).first():
            ch = CompanyHoliday(name=name, holiday_date=hdate, is_recurring=recurring, department='All')
            db.session.add(ch)
            print(f"  Added: {name} ({hdate})")
    db.session.commit()

    # =====================================================================
    # 2. TIME POLICIES
    # =====================================================================
    print("\n--- TIME POLICIES ---")
    if TimePolicy.query.count() == 0:
        policies = [
            ("Standard Office Hours", "All", time(9,0), time(18,0), 15, 8.0, 4.0, 6, True, 30),
            ("Engineering Flex", "Engineering", time(9,0), time(18,0), 30, 8.0, 4.0, 6, True, 30),
            ("HR Hours", "Human Resources", time(8,30), time(17,30), 15, 8.0, 3.0, 5, True, 45),
        ]
        for p in policies:
            tp = TimePolicy(name=p[0], department=p[1], shift_start=p[2], shift_end=p[3],
                          grace_period_minutes=p[4], max_regular_hours=p[5], max_overtime_hours=p[6],
                          max_consecutive_days=p[7], require_break=p[8], min_break_minutes=p[9])
            db.session.add(tp)
            print(f"  Added policy: {p[0]}")
        db.session.commit()

    # =====================================================================
    # 3. APPROVAL WORKFLOWS
    # =====================================================================
    print("\n--- APPROVAL WORKFLOWS ---")
    if ApprovalWorkflow.query.count() == 0:
        workflows = [
            ("Standard Leave Approval", "leave", None, True, 1, False, None, True),
            ("Sick Leave Auto-Approve", "leave", lt_sl.id, True, 1, True, "employee", True),
        ]
        for w in workflows:
            aw = ApprovalWorkflow(name=w[0], module=w[1], leave_type_id=w[2],
                                requires_approval=w[3], approval_levels=w[4],
                                auto_approve=w[5], auto_approve_role=w[6], notify_admins=w[7])
            db.session.add(aw)
            print(f"  Added workflow: {w[0]}")
        db.session.commit()

    # =====================================================================
    # 4. BUTTON PERMISSIONS
    # =====================================================================
    print("\n--- BUTTON PERMISSIONS ---")
    admin_role = Role.query.filter_by(name='admin').first()
    mgr_role = Role.query.filter_by(name='manager').first()
    buttons = [
        ("BUTTON_CALCULATE_CONTRIBUTIONS", "pf", admin_role),
        ("BUTTON_CALCULATE_PROFIT", "pf", admin_role),
        ("BUTTON_PROCESS_SETTLEMENT", "pf", admin_role),
        ("BUTTON_DISTRIBUTE_PROFIT", "pf", admin_role),
        ("BUTTON_APPROVE_PF_LOAN", "pf", admin_role),
        ("BUTTON_CALCULATE_CONTRIBUTIONS", "pf", mgr_role),
        ("BUTTON_VIEW_REPORTS", "reports", admin_role),
        ("BUTTON_VIEW_REPORTS", "reports", mgr_role),
    ]
    for code, module, role in buttons:
        if not ButtonPermission.query.filter_by(button_code=code, role_id=role.id).first():
            bp = ButtonPermission(role_id=role.id, button_code=code, is_granted=True, module=module)
            db.session.add(bp)
    db.session.commit()
    print(f"  Button permissions: {ButtonPermission.query.count()}")

    # =====================================================================
    # 5. ATTENDANCE (May 1 - July 12)
    # =====================================================================
    print("\n--- ATTENDANCE ---")
    att_count = 0
    for u in users:
        for d in weekdays:
            existing = Attendance.query.filter_by(user_id=u.id, date=d).first()
            if existing:
                continue
            # Skip holidays
            is_holiday = CompanyHoliday.query.filter_by(holiday_date=d).first()
            if is_holiday:
                continue

            # Determine attendance type
            rand = random.random()
            if rand < 0.05 and u.role_id == 3:  # 5% absent for employees
                status = 'absent'
                att = Attendance(user_id=u.id, date=d, status='absent', is_late=False, is_half_day=False)
                db.session.add(att)
                att_count += 1
                continue
            elif rand < 0.08 and u.role_id == 3:  # 3% half-day
                status = 'half-day'
                ci = random_clock()
                co_h = ci.hour + 4
                co = time(min(co_h, 23), ci.minute)
                is_late = ci > time(9, 15)
                att = Attendance(user_id=u.id, date=d, clock_in=datetime.combine(d, ci),
                               clock_out=datetime.combine(d, co), status=status,
                               is_late=is_late, is_half_day=True)
            elif rand < 0.12 and u.role_id == 3:  # 4% late
                ci = time(9, random.randint(16, 45))
                co = random_clock_out(ci)
                att = Attendance(user_id=u.id, date=d, clock_in=datetime.combine(d, ci),
                               clock_out=datetime.combine(d, co), status='present',
                               is_late=True, is_half_day=False)
            else:  # 88% present on time
                ci = time(8, random.randint(45, 59))
                co = random_clock_out(ci)
                att = Attendance(user_id=u.id, date=d, clock_in=datetime.combine(d, ci),
                               clock_out=datetime.combine(d, co), status='present',
                               is_late=False, is_half_day=False)

            db.session.add(att)
            db.session.flush()
            att_count += 1

            # Attendance log (after flush so att.id is set)
            if att.clock_in:
                log = AttendanceLog(attendance_id=att.id, event='clock_in',
                                  timestamp=att.clock_in, ip_address='192.168.1.100')
                db.session.add(log)
            if att.clock_out:
                log_out = AttendanceLog(attendance_id=att.id, event='clock_out',
                                      timestamp=att.clock_out, ip_address='192.168.1.100')
                db.session.add(log_out)

            # Break Log (lunch)
            if att.status == 'present' and not att.is_half_day and random.random() < 0.9 and att.clock_in:
                b_start_h = ci.hour + random.randint(1, 2)
                b_start = datetime.combine(d, time(min(b_start_h, 13), random.randint(0, 59)))
                b_dur = random.randint(25, 55)
                b_end = b_start + timedelta(minutes=b_dur)
                bl = BreakLog(attendance_id=att.id, break_start=b_start, break_end=b_end,
                            break_type='lunch', duration_minutes=b_dur)
                db.session.add(bl)

            # Overtime
            if att.status == 'present' and not att.is_half_day and att.clock_out and att.clock_out.time() > time(18, 0):
                co_t = att.clock_out.time()
                ot_hours = (co_t.hour - 18) + (co_t.minute / 60.0)
                if ot_hours > 0.5 and random.random() < 0.3:
                    existing_ot = OvertimeAccount.query.filter_by(user_id=u.id, date=d).first()
                    if not existing_ot:
                        ci_t = att.clock_in.time()
                        reg_h = min(8.0, (co_t.hour - ci_t.hour) + (co_t.minute - ci_t.minute) / 60.0)
                        ot = OvertimeAccount(user_id=u.id, date=d, regular_hours=reg_h,
                                           overtime_hours=ot_hours, approved=random.random() < 0.7)
                        db.session.add(ot)

        if att_count > 0 and att_count % 200 == 0:
            db.session.commit()
            print(f"    ... {att_count} attendance records so far")

db.session.commit()
actual = Attendance.query.count()
print(f"  Created {att_count} attendance records (total: {actual})")

    # Attendance Corrections (a few)
    print("\n--- ATTENDANCE CORRECTIONS ---")
    some_att = Attendance.query.filter(Attendance.clock_in.isnot(None)).limit(3).all()
    for a in some_att:
        if not AttendanceCorrection.query.filter_by(attendance_id=a.id).first():
            ac = AttendanceCorrection(attendance_id=a.id, corrected_by=admin.id,
                                     field='clock_in', old_value=str(a.clock_in.time()),
                                     new_value='09:00:00', reason='System auto-correction')
            db.session.add(ac)
    db.session.commit()
    print(f"  Created {len(some_att)} corrections")

    # =====================================================================
    # 6. LEAVE QUOTAS + REQUESTS
    # =====================================================================
    print("\n--- LEAVES ---")
    for u in users:
        for lt in leave_types:
            lq = LeaveQuota.query.filter_by(user_id=u.id, leave_type_id=lt.id, year=2026).first()
            if not lq:
                total = lt.default_quota
                if u.role_id == 1:
                    total = int(total * 1.2)
                lq = LeaveQuota(user_id=u.id, leave_type_id=lt.id, year=2026,
                               total=total, used=0, pending=0, remaining=total)
                db.session.add(lq)
    db.session.commit()

    # Leave requests
    leave_reasons = [
        "Family function", "Medical checkup", "Personal work",
        "Not feeling well", "Doctor's appointment", "Family emergency",
        "Vacation trip", "Religious event", "Home renovation"
    ]
    lr_count = 0
    for u in employees:
        for i in range(random.randint(1, 3)):
            ltype = random.choice(leave_types)
            days = random.randint(1, 3)
            start = date(2026, 5, random.randint(5, 25))
            end = start + timedelta(days=days - 1)
            if end > date(2026, 7, 10):
                continue
            existing = LeaveRequest.query.filter_by(user_id=u.id, start_date=start).first()
            if existing:
                continue
            # Check quota
            lq = LeaveQuota.query.filter_by(user_id=u.id, leave_type_id=ltype.id, year=2026).first()
            if not lq or lq.remaining < days:
                continue
            status = random.choice(['approved', 'approved', 'pending', 'approved'])
            lr = LeaveRequest(user_id=u.id, leave_type_id=ltype.id, start_date=start,
                            end_date=end, total_days=days,
                            reason=random.choice(leave_reasons), status=status)
            db.session.add(lr)
            db.session.flush()
            lr_count += 1

            # Update quota
            if status == 'approved':
                lq.used += days
                lq.remaining = lq.total - lq.used - lq.pending

            # Leave approval
            la = LeaveApproval(leave_request_id=lr.id, approver_id=mgr.id, level=1,
                             status='approved' if status == 'approved' else 'pending',
                             comment='Approved' if status == 'approved' else 'Pending review')
            db.session.add(la)
    db.session.commit()
    print(f"  Created {lr_count} leave requests")

    # Leave request for admin/manager too
    for u in [admin, mgr]:
        for i in range(random.randint(0, 1)):
            ltype = random.choice(leave_types)
            days = 1
            start = date(2026, 6, random.randint(5, 20))
            if LeaveRequest.query.filter_by(user_id=u.id, start_date=start).first():
                continue
            lr = LeaveRequest(user_id=u.id, leave_type_id=ltype.id, start_date=start,
                            end_date=start, total_days=days,
                            reason=random.choice(leave_reasons), status='approved')
            db.session.add(lr)
            db.session.flush()
            la2 = LeaveApproval(leave_request_id=lr.id, approver_id=admin.id if u.id != admin.id else mgr.id,
                              level=1, status='approved', comment='Self-approved')
            db.session.add(la2)
    db.session.commit()

    # =====================================================================
    # 7. TIMESHEETS (last 12 weeks from end_date)
    # =====================================================================
    print("\n--- TIMESHEETS ---")
    # Create projects first
    projects_data = [
        ("HRMS Portal", "HRMS-P1", "Employee self-service portal", "Engineering", mgr),
        ("Mobile App", "MOB-APP", "Mobile attendance app", "Engineering", mgr),
        ("Payroll Module", "PAY-V2", "Payroll version 2 upgrade", "Engineering", mgr),
        ("Data Analytics", "ANALYTICS", "HR analytics dashboard", "Engineering", mgr),
    ]
    proj_map = {}
    for pname, pcode, pdesc, pdept, ppm in projects_data:
        existing = Project.query.filter_by(code=pcode).first()
        if not existing:
            proj = Project(name=pname, code=pcode, description=pdesc, department=pdept,
                          project_manager_id=ppm.id, start_date=date(2026, 1, 1),
                          end_date=date(2026, 12, 31), status='active')
            db.session.add(proj)
            db.session.flush()
            proj_map[pcode] = proj
        else:
            proj_map[pcode] = existing
    db.session.commit()

    # Work packages
    wp_data = [
        ("HRMS-P1", ["User Management", "Leave Module", "Attendance Module"]),
        ("MOB-APP", ["GPS Tracking", "Push Notifications", "UI/UX"]),
        ("PAY-V2", ["Tax Calculation", "Bank Integration", "Payslip Generation"]),
        ("ANALYTICS", ["Data Pipeline", "Charts & Reports", "Export Module"]),
    ]
    wp_map = {}
    for pcode, packages in wp_data:
        proj = proj_map[pcode]
        for wp_name in packages:
            existing = WorkPackage.query.filter_by(project_id=proj.id, name=wp_name).first()
            if not existing:
                wp = WorkPackage(project_id=proj.id, name=wp_name, code=f"{pcode}-{wp_name[:3].upper()}",
                               description=f"Work package for {wp_name}", estimated_hours=random.randint(40, 160))
                db.session.add(wp)
                db.session.flush()
                wp_map[f"{pcode}-{wp_name}"] = wp
    db.session.commit()

    # Timesheet weeks
    ts_count = 0
    te_count = 0
    cur = end_date
    while cur >= start_date:
        if cur.weekday() == 6:  # Sunday
            week_end = cur
            week_start = cur - timedelta(days=6)
            if week_start < start_date:
                week_start = start_date
            for u in users:
                existing = TimesheetWeek.query.filter_by(user_id=u.id, week_start=week_start).first()
                if existing:
                    continue
                tw = TimesheetWeek(user_id=u.id, week_start=week_start, week_end=week_end,
                                 status='approved')
                db.session.add(tw)
                db.session.flush()
                total_hours = 0
                for d in daterange(week_start, week_end):
                    if is_weekend(d) or d > end_date:
                        continue
                    att = Attendance.query.filter_by(user_id=u.id, date=d).first()
                    hours = 0
                    if att and att.clock_in and att.clock_out and att.status in ('present', 'half-day'):
                        diff = (att.clock_out - att.clock_in).total_seconds() / 3600
                        hours = round(min(diff, 12), 1)
                        # Subtract break
                        br = BreakLog.query.filter_by(attendance_id=att.id).first()
                        if br and br.duration_minutes:
                            hours -= br.duration_minutes / 60.0
                        hours = max(0, round(hours, 1))
                    else:
                        hours = 0

                    if hours > 0:
                        proj = random.choice(list(proj_map.values()))
                        wp = WorkPackage.query.filter_by(project_id=proj.id).first()
                        te = TimesheetEntry(week_id=tw.id, day=d, project=proj.name,
                                          task=f"Work on {proj.name}", hours=hours,
                                          description=f"Regular work on {proj.name}")
                        db.session.add(te)
                        te_count += 1
                        total_hours += hours
                tw.total_hours = round(total_hours, 1)
                db.session.add(tw)
                ts_count += 1
                if tw.status == 'approved':
                    ta = TimesheetApproval(week_id=tw.id, approver_id=mgr.id, status='approved')
                    db.session.add(ta)
        cur -= timedelta(days=1)
    db.session.commit()
    print(f"  Created {ts_count} timesheet weeks, {te_count} entries")

    # =====================================================================
    # 8. OVERTIME
    # =====================================================================
    print("\n--- OVERTIME ---")
    ot_count = OvertimeAccount.query.count()
    print(f"  Total overtime records: {ot_count}")

    # =====================================================================
    # 9. COMPENSATION / PAYROLL
    # =====================================================================
    print("\n--- PAYROLL ---")
    # Ensure profiles exist for all
    for u in users:
        pp = PayrollProfile.query.filter_by(user_id=u.id).first()
        if not pp:
            if u.role_id == 1:
                basic = 200000
            elif u.role_id == 2:
                basic = 150000
            else:
                basic = {3: 80000, 4: 70000, 5: 90000}.get(u.id, 80000)
            pp = PayrollProfile(user_id=u.id, basic_salary=basic, effective_from=date(2026, 1, 1))
            db.session.add(pp)
            db.session.flush()
            comps = [
                ("House Rent", "allowance", "percentage", 40, False),
                ("Medical Allowance", "allowance", "fixed", 15000, False),
                ("Conveyance Allowance", "allowance", "fixed", 10000, False),
            ]
            for cname, ctype, cmethod, cval, ctax in comps:
                pc = PayrollComponent(profile_id=pp.id, name=cname, type=ctype,
                                    calculation_method=cmethod, value=cval, is_taxable=ctax)
                db.session.add(pc)
    db.session.commit()

    # Payroll runs for May, June, July
    for m, y, st in [(5, 2026, 'completed'), (6, 2026, 'completed'), (7, 2026, 'draft')]:
        pr = PayrollRun.query.filter_by(month=m, year=y).first()
        if pr:
            continue
        run_date = datetime(y, m, 1)
        pr = PayrollRun(month=m, year=y, run_date=run_date, status=st,
                       processed_by=admin.id, employee_count=len(users))
        if st == 'completed':
            pr.approved_by = admin.id
            pr.approved_at = run_date + timedelta(days=5)
        db.session.add(pr)
        db.session.flush()

        # Slips for each user
        total_gross = 0
        total_ded = 0
        total_net = 0
        for u in users:
            pp = PayrollProfile.query.filter_by(user_id=u.id).first()
            if not pp:
                continue
            basic = pp.basic_salary or 0
            house_rent = basic * 0.4
            medical = 15000
            conveyance = 10000
            allowances = house_rent + medical + conveyance
            gross = basic + allowances
            pf_emp = gross * 0.05
            tax = 0
            if gross > 60000:
                tax = gross * 0.05
            loan_ded = 0
            total_deductions = pf_emp + tax + loan_ded
            net = gross - total_deductions
            comps_json = json.dumps([
                {"name":"Basic Salary","type":"earning","amount":basic},
                {"name":"House Rent","type":"earning","amount":house_rent},
                {"name":"Medical Allowance","type":"earning","amount":medical},
                {"name":"Conveyance","type":"earning","amount":conveyance},
                {"name":"Provident Fund","type":"deduction","amount":pf_emp},
                {"name":"Income Tax","type":"deduction","amount":tax},
            ])
            slip = PayrollSlip.query.filter_by(payroll_run_id=pr.id, user_id=u.id).first()
            if not slip:
                slip = PayrollSlip(payroll_run_id=pr.id, user_id=u.id, basic_salary=basic,
                                 allowances=allowances, deductions=loan_ded,
                                 gross_pay=gross, total_deductions=total_deductions,
                                 net_pay=net, components_json=comps_json)
                db.session.add(slip)
            total_gross += gross
            total_ded += total_deductions
            total_net += net

            # PF contributions
            existing_pf = PFContribution.query.filter_by(user_id=u.id, month=m, year=y).first()
            if not existing_pf:
                pfc = PFContribution(user_id=u.id, month=m, year=y,
                                    employee_amount=pf_emp, employer_amount=pf_emp,
                                    total_amount=pf_emp * 2)
                db.session.add(pfc)

                pf_ledger_entry = PFLedger(user_id=u.id, transaction_date=date(y, m, 1),
                                         transaction_type='contribution',
                                         description=f'PF Contribution for {m}/{y}',
                                         credit=pf_emp * 2, balance=pf_emp * 2 * pr.id if pr.id else pf_emp * 2)
                db.session.add(pf_ledger_entry)

        pr.total_gross = total_gross
        pr.total_deductions = total_ded
        pr.total_net = total_net
        db.session.commit()
        print(f"  Payroll run {m}/{y}: status={st}, net={total_net}")

    # Salary revisions
    print("\n--- SALARY REVISIONS ---")
    for u in employees:
        if not SalaryRevision.query.filter_by(user_id=u.id).first():
            pp = PayrollProfile.query.filter_by(user_id=u.id).first()
            if pp:
                sr = SalaryRevision(user_id=u.id, previous_basic=pp.basic_salary,
                                   new_basic=pp.basic_salary * 1.1,
                                   reason="Annual performance increment",
                                   approved_by=mgr.id, effective_from=date(2026, 7, 1))
                db.session.add(sr)
    db.session.commit()
    print(f"  Created salary revisions")

    # =====================================================================
    # 10. PF WITHDRAWALS & LOANS
    # =====================================================================
    print("\n--- PF TRANSACTIONS ---")
    for u in employees:
        if not PFWithdrawalRequest.query.filter_by(user_id=u.id).first():
            if random.random() < 0.5:
                pfw = PFWithdrawalRequest(user_id=u.id, amount=random.randint(50000, 200000),
                                        reason="Home renovation", status='approved',
                                        approved_by=admin.id, approved_at=datetime(2026, 6, 15))
                db.session.add(pfw)
                # Ledger
                led = PFLedger(user_id=u.id, transaction_date=date(2026, 6, 15),
                             transaction_type='withdrawal', description='PF Withdrawal for renovation',
                             debit=pfw.amount, balance=0)
                db.session.add(led)

    for u in employees:
        if not PFLoanRequest.query.filter_by(user_id=u.id).first():
            if random.random() < 0.4:
                amt = random.randint(100000, 300000)
                pfl = PFLoanRequest(user_id=u.id, amount=amt, installment_months=12,
                                  purpose="Education expenses", status='approved',
                                  approved_by=admin.id, approved_at=datetime(2026, 5, 10),
                                  monthly_installment=amt / 12, remaining_amount=amt - (amt / 12) * 2)
                db.session.add(pfl)
    db.session.commit()
    print(f"  PF withdrawals: {PFWithdrawalRequest.query.count()}, loans: {PFLoanRequest.query.count()}")

    # PF Profit Distribution
    if not PFProfitDistribution.query.first():
        ppd = PFProfitDistribution(month=6, year=2026, total_profit=500000,
                                 distributed_by=admin.id, status='completed')
        db.session.add(ppd)
        db.session.commit()
        print("  Added PF profit distribution")

    # =====================================================================
    # 11. LOANS (Salary advances)
    # =====================================================================
    print("\n--- SALARY LOANS ---")
    for u in employees:
        if not LoanAdvanceRequest.query.filter_by(user_id=u.id).first():
            if random.random() < 0.5:
                amt = random.randint(30000, 100000)
                installments = random.choice([6, 12])
                lar = LoanAdvanceRequest(user_id=u.id, request_type='advance', amount=amt,
                                       purpose="Personal expense", installment_months=installments,
                                       monthly_installment=amt / installments,
                                       remaining_amount=amt - (amt / installments),
                                       status='disbursed', approved_by=mgr.id,
                                       approved_at=datetime(2026, 5, 20), queue_for_payroll=True)
                db.session.add(lar)
                db.session.flush()
                # Repayment
                lr = LoanRepayment(loan_id=lar.id, amount=lar.monthly_installment,
                                 paid_at=datetime(2026, 6, 1), notes='June repayment')
                db.session.add(lr)
    db.session.commit()
    print(f"  Loan requests: {LoanAdvanceRequest.query.count()}")

    # =====================================================================
    # 12. PERFORMANCE
    # =====================================================================
    print("\n--- PERFORMANCE ---")
    for u in employees:
        if not PerformanceReview.query.filter_by(user_id=u.id).first():
            pr = PerformanceReview(user_id=u.id, reviewer_id=mgr.id, review_period='H1-2026',
                                 overall_score=random.uniform(3.0, 4.8),
                                 productivity_rating=random.randint(3, 5),
                                 quality_rating=random.randint(3, 5),
                                 teamwork_rating=random.randint(3, 5),
                                 punctuality_rating=random.randint(3, 5),
                                 strengths='Good team player, meets deadlines',
                                 improvements='Could improve documentation',
                                 feedback='Solid performance this half', status='completed',
                                 completed_at=datetime(2026, 6, 30))
            db.session.add(pr)

        for g in ["Complete HRMS module", "Improve test coverage", "Document APIs"]:
            if not PerformanceGoal.query.filter_by(user_id=u.id, title=g).first():
                pg = PerformanceGoal(user_id=u.id, title=g,
                                   description=f"Goal: {g.lower()}",
                                   target_date=date(2026, 12, 31),
                                   status=random.choice(['active', 'completed', 'active']),
                                   progress_pct=random.randint(30, 100),
                                   created_by=mgr.id)
                db.session.add(pg)
    db.session.commit()
    print(f"  Reviews: {PerformanceReview.query.count()}, Goals: {PerformanceGoal.query.count()}")

    # =====================================================================
    # 13. DIGITAL FILES
    # =====================================================================
    print("\n--- DIGITAL FILES ---")
    for u in employees:
        for cat in file_cats[:3]:
            if not DigitalFile.query.filter_by(user_id=u.id, category_id=cat.id).first():
                df = DigitalFile(user_id=u.id, category_id=cat.id,
                               title=f"{cat.name} - {u.full_name}",
                               filename=f"uuid_{u.id}_{cat.id}.pdf",
                               original_name=f"{cat.name.lower().replace(' ','_')}_{u.employee_code}.pdf",
                               file_size=random.randint(50000, 500000),
                               mime_type='application/pdf',
                               notes=f"Uploaded {cat.name} document",
                               is_verified=random.random() < 0.7,
                               verified_by=admin.id if random.random() < 0.7 else None)
                db.session.add(df)
    db.session.commit()
    print(f"  Digital files: {DigitalFile.query.count()}")

    # =====================================================================
    # 14. NOTIFICATIONS
    # =====================================================================
    print("\n--- NOTIFICATIONS ---")
    notif_types = ['info', 'success', 'warning', 'error']
    notifs = [
        ("Payroll Processed", "May 2026 payroll has been processed successfully.", "success", "payroll"),
        ("Leave Approved", "Your annual leave request has been approved.", "success", "leave"),
        ("PF Contribution Updated", "Provident fund contributions for June are updated.", "info", "pf"),
        ("Time Policy Change", "Office hours have been updated. Please review.", "warning", "attendance"),
        ("New Announcement", "Company-wide meeting on Friday at 3 PM.", "info", "workplace"),
        ("Performance Review", "H1 performance reviews are due by June 30.", "warning", "performance"),
        ("System Maintenance", "System will be down on Saturday 2-4 AM.", "error", "system"),
        ("Document Expiry", "Your CNIC document is expiring soon.", "warning", "digital_files"),
    ]
    for title, msg, ntype, module in notifs:
        existing = Notification.query.filter_by(title=title).first()
        if existing:
            continue
        n = Notification(title=title, message=msg, notification_type=ntype, module=module, created_by=admin.id)
        db.session.add(n)
        db.session.flush()
        for u in users:
            nr = NotificationRecipient(notification_id=n.id, user_id=u.id,
                                      is_read=random.random() < 0.4)
            db.session.add(nr)

    # Email logs
    for u in employees:
        if not EmailLog.query.filter_by(recipient=u.email).first():
            el = EmailLog(recipient=u.email, subject='Payslip for June 2026',
                        body=f'Dear {u.full_name}, your payslip is ready.',
                        module='payroll', status='sent')
            db.session.add(el)
    db.session.commit()
    print(f"  Notifications: {Notification.query.count()}, Emails: {EmailLog.query.count()}")

    # =====================================================================
    # 15. CHANGE REQUESTS
    # =====================================================================
    print("\n--- CHANGE REQUESTS ---")
    change_fields = [
        ("phone", "0300-1234567", "0300-9876543"),
        ("emergency_contact", "Father", "Brother"),
        ("emergency_phone", "0300-1111111", "0300-2222222"),
        ("address", "Old Address", "New Address, City"),
    ]
    for u in employees:
        if not ChangeRequest.query.filter_by(user_id=u.id).first():
            field, old_val, new_val = random.choice(change_fields)
            cr = ChangeRequest(user_id=u.id, field_name=field, old_value=old_val,
                             new_value=new_val, status=random.choice(['pending', 'approved', 'approved']))
            if cr.status == 'approved':
                cr.reviewed_by = admin.id
                cr.reviewed_at = datetime(2026, 6, 20)
            db.session.add(cr)
    db.session.commit()
    print(f"  Change requests: {ChangeRequest.query.count()}")

    # =====================================================================
    # 16. WORKPLACE - Announcements, Events, Kanban
    # =====================================================================
    print("\n--- WORKPLACE ---")
    announcements = [
        ("Welcome to Q2 2026", "Team, we have achieved great results this quarter.", "high", admin),
        ("Office Timings Update", "Summer timings: 8:30 AM to 5:30 PM effective May 1.", "urgent", admin),
        ("Team Outing", "Annual team outing scheduled for June 20.", "normal", mgr),
        ("New Hire Orientation", "Please welcome our new team members.", "normal", admin),
    ]
    for title, content, priority, author in announcements:
        if not Announcement.query.filter_by(title=title).first():
            a = Announcement(title=title, content=content, priority=priority,
                           author_id=author.id,
                           pinned=(priority == 'urgent'),
                           expires_at=date(2026, 12, 31))
            db.session.add(a)

    events = [
        ("Q2 Town Hall", "Quarterly company meeting", date(2026, 5, 15), time(14,0), time(16,0), "Conference Room A", "meeting", admin),
        ("Team Lunch", "Team building lunch", date(2026, 6, 10), time(13,0), time(14,30), "Downtown Restaurant", "social", mgr),
        ("Birthday Celebration", "Monthly birthday celebration", date(2026, 6, 20), time(16,0), time(17,0), "Office Cafeteria", "birthday", admin),
        ("Training Workshop", "Advanced Python workshop", date(2026, 7, 5), time(10,0), time(13,0), "Training Room", "training", mgr),
    ]
    for title, desc, edate, st, et, loc, etype, creator_obj in events:
        if not TeamEvent.query.filter_by(title=title).first():
            ev = TeamEvent(title=title, description=desc, event_date=edate,
                         start_time=st, end_time=et, location=loc, event_type=etype,
                         created_by=creator_obj.id)
            db.session.add(ev)

    # Kanban
    board = KanbanBoard.query.first()
    if board:
        kanban_tasks_data = [
            ("Setup CI/CD pipeline", "todo", "high", 3),
            ("Complete API documentation", "in-progress", "medium", 3),
            ("Fix login bug", "done", "urgent", 4),
            ("Database optimization", "todo", "medium", 5),
            ("Code review PR #42", "in-progress", "high", 3),
            ("Update dependencies", "todo", "low", 5),
            ("Write unit tests", "done", "medium", 4),
            ("Deploy to staging", "done", "high", 5),
        ]
        for title, status, priority, assignee_id in kanban_tasks_data:
            if not KanbanTask.query.filter_by(board_id=board.id, title=title).first():
                kt = KanbanTask(board_id=board.id, title=title, status=status,
                              priority=priority, assignee_id=assignee_id,
                              due_date=date(2026, 7, 15), position=0)
                db.session.add(kt)
    else:
        board = KanbanBoard(title="Engineering Tasks", description="Engineering team kanban board",
                          created_by=admin.id)
        db.session.add(board)
        db.session.flush()
        for title, status, priority, assignee_id in [
            ("Setup CI/CD pipeline", "todo", "high", 3),
            ("Complete API documentation", "in-progress", "medium", 3),
            ("Fix login bug", "done", "urgent", 4),
        ]:
            kt = KanbanTask(board_id=board.id, title=title, status=status,
                          priority=priority, assignee_id=assignee_id,
                          due_date=date(2026, 7, 15))
            db.session.add(kt)

    db.session.commit()
    print(f"  Announcements: {Announcement.query.count()}")
    print(f"  Events: {TeamEvent.query.count()}")
    print(f"  Kanban tasks: {KanbanTask.query.count()}")

    # =====================================================================
    # 17. PF SETTLEMENTS (for one user)
    # =====================================================================
    if not PFSettlement.query.first():
        u = employees[0]
        total_emp = sum(c.employee_amount for c in PFContribution.query.filter_by(user_id=u.id).all())
        total_empyer = sum(c.employer_amount for c in PFContribution.query.filter_by(user_id=u.id).all())
        ps = PFSettlement(user_id=u.id, total_employee_contrib=total_emp,
                         total_employer_contrib=total_empyer, total_profit_distributed=5000,
                         outstanding_loan=0, net_settlement=total_emp + total_empyer + 5000,
                         status='pending')
        db.session.add(ps)
        db.session.commit()
        print("  Added PF settlement")

    # =====================================================================
    # SUMMARY
    # =====================================================================
    print("\n" + "="*60)
    print("SEEDING COMPLETE")
    print("="*60)
    tables = [
        ('Attendance', Attendance), ('AttendanceLog', AttendanceLog),
        ('BreakLog', BreakLog), ('AttendanceCorrection', AttendanceCorrection),
        ('LeaveQuota', LeaveQuota), ('LeaveRequest', LeaveRequest),
        ('LeaveApproval', LeaveApproval),
        ('TimesheetWeek', TimesheetWeek), ('TimesheetEntry', TimesheetEntry),
        ('TimesheetApproval', TimesheetApproval),
        ('PayrollProfile', PayrollProfile), ('PayrollComponent', PayrollComponent),
        ('PayrollRun', PayrollRun), ('PayrollSlip', PayrollSlip),
        ('SalaryRevision', SalaryRevision),
        ('PFContribution', PFContribution), ('PFLedger', PFLedger),
        ('PFWithdrawalRequest', PFWithdrawalRequest), ('PFLoanRequest', PFLoanRequest),
        ('PFProfitDistribution', PFProfitDistribution), ('PFSettlement', PFSettlement),
        ('Project', Project), ('WorkPackage', WorkPackage), ('ProjectTask', ProjectTask),
        ('DigitalFile', DigitalFile),
        ('Notification', Notification), ('NotificationRecipient', NotificationRecipient),
        ('EmailLog', EmailLog),
        ('LoanAdvanceRequest', LoanAdvanceRequest), ('LoanRepayment', LoanRepayment),
        ('PerformanceReview', PerformanceReview), ('PerformanceGoal', PerformanceGoal),
        ('CompanyHoliday', CompanyHoliday), ('TimePolicy', TimePolicy),
        ('ApprovalWorkflow', ApprovalWorkflow), ('OvertimeAccount', OvertimeAccount),
        ('ChangeRequest', ChangeRequest),
        ('Announcement', Announcement), ('TeamEvent', TeamEvent),
        ('KanbanBoard', KanbanBoard), ('KanbanTask', KanbanTask),
        ('ButtonPermission', ButtonPermission),
    ]
    for name, cls in tables:
        cnt = cls.query.count()
        print(f"  {name:35s}: {cnt:4d}")
