#! /usr/bin/python
# Disk Health Check Script from Randall Mawhinnie
import commands , sys ,psycopg2 , topology , itertools , time

# Function to query Postgre database
def calldb(dbhost, db, sql):
    # import psycopg2
    params = {
        'database': db,
        'user': 'postgres',
        'host': dbhost,
    }
    conn = psycopg2.connect(**params)
    cur = conn.cursor()
    cur.execute(sql)
    dbout = cur.fetchall()
    conn.close()
    return dbout

# Function to Find system topology
def getmasters():
    # import topology
    systemMaster = (topology.get_system_master())
    rmgMasters   = (topology.get_all_masters())
    rmgOneNodes  = (topology.get_rmg_nodelist(rmgMasters[0].split('-')[0]))
    rmgTwoNodes  = (topology.get_rmg_nodelist(rmgMasters[1].split('-')[0]))
    return systemMaster , rmgMasters , rmgOneNodes , rmgTwoNodes

# Function to Find mount point
def mounts(host, fsuuid):
    # import commands
    mounts = commands.getoutput('ssh ' + host + ' df | grep ' + fsuuid)
    ssmount = ssutil = mdsmount = mdsutil = None
    for mount in mounts.split('\n'):
        if mount:
            mount = mount.split()
            if 'mauiss' in mount[5]:
                ssmount = mount[5]
                ssutil = mount[4]
            elif 'atmos' in mount[5]:
                mdsmount = mount[5]
                mdsutil = mount[4]
    return ssmount, ssutil, mdsmount, mdsutil

# Function to Make Patrick Happy (check peer mds for init)
def mdsHC(host, port):
    # import commands
    getMdsSet = 'mauisvcmgr -s mauimds -c mauimds_getMdsSet -m' + host + ':' + port
    mdsSet = commands.getoutput(getMdsSet).split('\n')
    mdshost = []
    mdsport = []
    mdshealth = []
    for line in mdsSet:
        if 'host' in line:
            line = line.split('>')[1].split('<')[0]
            mdshost.append(line)
        if 'port' in line:
            line = line.split('>')[1].split('<')[0]
            mdsport.append(line)
    for i in range(len(mdshost)):
        mdsquery = 'mauisvcmgr -s mauimds -c mauimds_isNodeInitialized -m' + mdshost[i] + ':' + mdsport[i]
        mdsinit = commands.getoutput(mdsquery).split('\n')[1]
        if 'true' not in mdsinit:
            mdshealth.append(mdshost[i] + ':' + mdsport[i])
    return mdshealth

# Function to make John Happy
def spinner(end):
    # import itertools, sys, time
    spinner = itertools.cycle(['-', '/', '|', '\\'])
    count = 0
    while int(count) < int(end) * 10:
        sys.stdout.write(spinner.next())  # write the next character
        sys.stdout.flush()  # flush stdout buffer (actual character display)
        sys.stdout.write('\b')  # erase the last written char
        time.sleep(0.1)
        count += 1

# Gather Data about disk
if len(sys.argv) > 1:
    diskentered = sys.argv[1]
else:
    diskentered = raw_input('Please enter Disk UUID or the FSUUID : ')
diskentered = diskentered.strip().strip('\'')

# Find info on Disk from RMG Database
sytemMaster , rmgMasters , rmgOneNodes , rmgTwoNodes = getmasters()
if len(diskentered) <= 8:
    diskinfosql = "SELECT nodes.hostname, disks.devpath , fsdisks.fsuuid, disks.uuid , disks.status , disks.slot_replaced from disks JOIN nodes on nodes.uuid=disks.nodeuuid JOIN fsdisks on disks.uuid=fsdisks.diskuuid where disks.uuid = '" + diskentered + "';"
elif len(diskentered) > 8:
    diskinfosql = "SELECT nodes.hostname, disks.devpath , fsdisks.fsuuid, disks.uuid , disks.status , disks.slot_replaced from disks JOIN nodes on nodes.uuid=disks.nodeuuid JOIN fsdisks on disks.uuid=fsdisks.diskuuid where fsdisks.fsuuid = '" + diskentered + "';"
if calldb(rmgMasters[0], 'rmg.db', diskinfosql):
    diskinfo = calldb(rmgMasters[0], 'rmg.db', diskinfosql)
    rmgMaster = rmgMasters[0]
    diskType = 'DAE'
    host = diskinfo[0][0]
    disk = diskinfo[0][1]
    fsuuid = diskinfo[0][2]
    uuid = diskinfo[0][3]
    diskdbstatus = diskinfo[0][4]
    diskreplaced = diskinfo[0][5]
elif calldb(rmgMasters[1], 'rmg.db', diskinfosql):
    diskinfo = calldb(rmgMasters[1], 'rmg.db', diskinfosql)
    rmgMaster = rmgMasters[1]
    diskType = 'DAE'
    host = diskinfo[0][0]
    disk = diskinfo[0][1]
    fsuuid = diskinfo[0][2]
    uuid = diskinfo[0][3]
    diskdbstatus = diskinfo[0][4]
    diskreplaced = diskinfo[0][5]
else:                       # Hail Marry pas
    print 'Unable to locate disk'

mdsOnDisk = []
mdsheath = []
diskpart = commands.getoutput('ssh ' + host + " 'sg_map | grep " + disk + "'")
if diskpart: diskpart = diskpart.split()[0]
ssmount, ssutil, mdsmount, mdsutil = mounts(host, fsuuid)
mdsDirDisk = commands.getoutput('ssh ' + host + " 'grep " + fsuuid + " /etc/maui/mds/*/mds_cfg.xml'")
tla = commands.getoutput('ssh ' + host + " 'grep hardwareTLA /etc/maui/reporting/tla_reporting.conf'").split()[2]

disksdbtatuscode = {  1: 'Running',
                      2: 'Pending Add',
                      3: 'Pending Remove',
                      4: 'Removed',
                      5: 'Non-Critical Failure',
                      6: 'Critical Failure',
                      7: 'Partitioning',
                      8: 'Add failed',
                     36: 'Removed + recovery complete (SS Disk Only)',
                     38: 'Error + recovery complete (SS Disk Only)',
                     52: 'Error + recovery complete + replaced (MDS Disk Only)',
                     54: 'Error + recovery complete + replaced (MDS Disk Only)',
                    204: 'Unspecified',
                    255: 'Unspecified'}

recoverystatus = {0: 'RECOVERY_START',
                  1: 'RECOVERY_CANCELED',
                  2: 'RECOVERY_COMPLETE',
                  3: 'RECOVERY_IN_PROGRESS',
                  4: 'RECOVERY_ABORTING',
                  5: 'RECOVERY_FAILED',
                  6: 'RECOVERY_PENDING'}
if mdsDirDisk:
    mdsDirDisk = mdsDirDisk.split('\n')
    for mds in mdsDirDisk:
        mdsOnDisk.append(mds.split(':')[0].split('/')[4])

# Verify disk health
print 'Following Knowledge Base Article: 000015022'
if (int(diskdbstatus) == 4 ) or (int(diskreplaced) == 1):
    print 'Disk is removed from system, unable to check Disk Health'
    exit()
if ssmount or mdsmount :
    print "Disk is currently mounted as fsuuid ", fsuuid
else :
    print "Disk is not mounted"
# Run smart test and Check for failed sector count
if mdsOnDisk: print 'Found ', host, ':', (", ".join(mdsOnDisk)), 'MDS on disk'
else : print 'No MDS found on disk'
for i in range(len(mdsOnDisk)):
    if mdsHC(host, mdsOnDisk[i]):
        mdsheath.append(mdsHC(host, mdsOnDisk[i]))
if mdsheath: print 'Found error reporting in peer mds', (", ".join(mdsheath))
print 'Starting Smart Test on', disk, 'on', host, ' please wait for completion'
smarttest = 'smartctl --test=short ' + disk
runsmartest = commands.getoutput(smarttest)
failseccount = 'ssh ' + host + ' cs_hal info ' + diskpart + "| grep SMART"
spinner('5')
while ('in progress' or 'Cannot allocate memory') in commands.getoutput(failseccount):
    spinner('5')

diskhealthstatus = commands.getoutput(failseccount)
smartout = commands.getoutput('ssh ' + host + ' smartctl -a ' + diskpart + " | egrep 'Reallocated_|_Uncorr|_Pending'")
smartout = smartout.split('\n')
for line in smartout:
    line = line.split()
    if 'Reallocated_Sector_Ct' in line[1]: seccount = line[9]
    if 'Reallocated_Event_Count' in line[1]: realocEvntCt = line[9]
    if 'Current_Pending_Sector' in line[1]: curPendSect = line[9]
    if 'Offline_Uncorrectable' in line[1]: uncorrectSect = line[9]

# Determine Health of Disk
dbdiskstatusdesc = disksdbtatuscode.get(int(diskdbstatus))
print 'RMG database shows disk as :', dbdiskstatusdesc
if 'GOOD' in diskhealthstatus:
    diskhealth = 'GOOD'
    print 'Disk', disk, 'on', host, 'is Healthy.'
elif 'SUSPECT' in diskhealthstatus:
    diskhealth = diskhealthstatus.split(':')[1].strip()
    print 'Disk', disk, 'on', host, 'is suspect, with', seccount, ' reallocated sectors, ' + curPendSect + ' Pending Sectors and ' + uncorrectSect + ' failed secorts'
elif (diskhealthstatus.split(':')[1].strip() == 'FAILED') or (int(uncorrectSect) > 10):
    diskhealth = diskhealthstatus.split(':')[1].strip()
    if mdsOnDisk: print 'MDS ', (", ".join(mdsOnDisk)), 'still pointing to ', fsuuid
    print 'Disk', disk, 'on', host, 'is failed, with', seccount, ' reallocated sectors, ' + curPendSect + ' Pending Sectors and ' + uncorrectSect + ' failed secorts'
    recoverysql = "SELECT fsdisks.fsuuid , disks.slot , disks.status , recoverytasks.starttime ,recoverytasks.status , recoverytasks.unrecoverobj FROM disks  JOIN fsdisks ON disks.uuid=fsdisks.diskuuid  FULL OUTER JOIN recoverytasks ON fsdisks.fsuuid=recoverytasks.fsuuid  FULL OUTER JOIN nodes ON disks.nodeuuid=nodes.uuid where disks.uuid = '" + uuid + "';"
    recoveryinfo = calldb(rmgMaster, 'rmg.db', recoverysql)
    print 'FSUUID              :', recoveryinfo[0][0]
    print 'Disk Slot           :', recoveryinfo[0][1]
    print 'Disk Status         :', recoveryinfo[0][2]
    print 'Recovery Start Time :', recoveryinfo[0][3]
    print 'Recovery Status     :', recoverystatus.get(recoveryinfo[0][4])
    print 'Unrecovered Objects :', recoveryinfo[0][5]
else:
    diskhealth = 'Unknown'
    print diskhealthstatus

# check for XFS corruption on node and repair

xfscheckcommand = 'ssh ' + host + ' "/bin/dmesg | grep ' + disk.lstrip('/dev/') + '|grep XFS"'
xfs_corrupt = commands.getoutput(xfscheckcommand)

if ('Corruption' in xfs_corrupt) or ('page discard on page' in xfs_corrupt):
    xfsstatus = 'Possible Corruption found on disk'
    print xfsstatus
    xfs_corrupt = xfs_corrupt.split('\n')
    for line in xfs_corrupt:
        if ('Corruption' in line) or ('page discard on page' in line):
            print line
else:
    xfsstatus = 'No XFS Corruption found'
    print xfsstatus

# Report on Disk Health
print ''
print 'Disk Health Report'
print '#'*68
print 'Host                           :', host
print 'Sys. Serial#                   :', tla
print 'Disk UUID                      :', uuid
print 'Dev Path                       :', disk
print 'FSUUID                         :', fsuuid
if ssmount:   print 'SS Mount                       :', ssmount, ssutil
if mdsmount:  print 'MDS Mount                      :', mdsmount, mdsutil
if not (ssmount or mdsmount):
    print 'Mount Info                     : No mount point found'
if diskhealth != 'FAILED' and not (ssmount or mdsmount):
    print 'Disk Mount Status              :', 'Disk health shows ', diskhealth, ' but not mounted'
if diskhealth == 'FAILED' and (ssmount or mdsmount):
    print 'Mount Note                     : AlertDisk health is failed but currently mounted'
if diskhealth == 'FAILED' : print 'Recovery Status                :', recoverystatus.get(recoveryinfo[0][4])
if mdsOnDisk: print 'MDS on Disk                    :', (", ".join(mdsOnDisk))
if mdsheath:  print 'Peer MDS reporting error       :', (", ".join(mdsheath))
print 'XFS Status                     :', xfsstatus
print 'Disk Database status           :', dbdiskstatusdesc
print 'Smart Health                   :', diskhealth
if diskhealth != 'GOOD' :
    print '  Reallocated Sector Count     :', seccount
    print '  Reallocated Event Count      :', realocEvntCt
    print '  Current Pending Sector Count :', curPendSect
    print '  Offline Uncorrectable Count  :', uncorrectSect
print '#'*68
