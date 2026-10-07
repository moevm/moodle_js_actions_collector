<?php
define('CLI_SCRIPT', true);
require('/var/www/html/config.php');
require_once($CFG->dirroot . '/course/lib.php');
require_once($CFG->dirroot . '/course/modlib.php');
require_once($CFG->dirroot . '/user/lib.php');
require_once($CFG->libdir . '/enrollib.php');
require_once($CFG->libdir . '/questionlib.php');
require_once($CFG->dirroot . '/mod/quiz/locallib.php');

\core\session\manager::set_user(get_admin());
set_config('enabled', 1, 'local_actioncollector');
set_config('apiurl', getenv('COLLECTOR_API_URL'), 'local_actioncollector');
set_config('enablecompletion', 1);

function lab_user($username, $firstname, $lastname, $password) {
    global $DB, $CFG;
    $user = $DB->get_record('user', ['username' => $username, 'mnethostid' => $CFG->mnet_localhost_id]);
    if ($user) { return $user->id; }
    return user_create_user((object)[
        'username' => $username, 'password' => $password,
        'firstname' => $firstname, 'lastname' => $lastname,
        'email' => $username . '@example.com', 'auth' => 'manual',
        'confirmed' => 1, 'mnethostid' => $CFG->mnet_localhost_id,
        'lang' => 'en', 'city' => 'Moscow', 'country' => 'RU',
    ]);
}

$studentid = lab_user('student', 'Test', 'Student', getenv('MOODLE_STUDENT_PASSWORD'));
$teacherid = lab_user('teacher', 'Test', 'Teacher', getenv('MOODLE_TEACHER_PASSWORD'));
$course = $DB->get_record('course', ['shortname' => 'COLLECTOR-DEMO']);
if (!$course) {
    $categoryid = $DB->get_field('course_categories', 'id', [], IGNORE_MULTIPLE);
    $course = create_course((object)[
        'fullname' => 'Collector Demo Course', 'shortname' => 'COLLECTOR-DEMO',
        'category' => $categoryid, 'format' => 'topics', 'numsections' => 1,
        'visible' => 1, 'enablecompletion' => 1,
        'summary' => 'Manual checks: reading, scrolling, clipboard, quiz attempts and assignment submission.',
        'summaryformat' => FORMAT_HTML,
    ]);
}
$enrolplugin = enrol_get_plugin('manual');
$instance = null;
foreach (enrol_get_instances($course->id, false) as $candidate) {
    if ($candidate->enrol === 'manual') { $instance = $candidate; break; }
}
if (!$instance) {
    $id = $enrolplugin->add_instance($course, ['status' => ENROL_INSTANCE_ENABLED]);
    $instance = $DB->get_record('enrol', ['id' => $id], '*', MUST_EXIST);
}
foreach (['student' => $studentid, 'editingteacher' => $teacherid] as $role => $userid) {
    $roleid = $DB->get_field('role', 'id', ['shortname' => $role], MUST_EXIST);
    $enrolplugin->enrol_user($instance, $userid, $roleid);
}

function lab_module($course, $type, $idnumber, $name, array $extra) {
    global $DB;
    $cm = $DB->get_record('course_modules', ['course' => $course->id, 'idnumber' => $idnumber]);
    if ($cm) { return $cm; }
    $moduleinfo = (object)array_merge([
        'modulename' => $type, 'module' => $DB->get_field('modules', 'id', ['name' => $type], MUST_EXIST),
        'name' => $name, 'section' => 1, 'visible' => 1, 'cmidnumber' => $idnumber,
        'intro' => '', 'introformat' => FORMAT_HTML, 'groupmode' => 0,
        'completion' => COMPLETION_TRACKING_MANUAL,
    ], $extra);
    $result = add_moduleinfo($moduleinfo, $course);
    return get_coursemodule_from_id($type, $result->coursemodule, $course->id, false, MUST_EXIST);
}

$paragraphs = '';
for ($i = 1; $i <= 35; $i++) {
    $paragraphs .= '<p>Section ' . $i . ': this is a long sample material for checking page scrolling. '
        . 'Select this text and copy it, then paste it into the assignment answer.</p>';
}
$page = lab_module($course, 'page', 'collector-reading', 'Reading and scrolling', [
    'content' => '<h2>Collector demo material</h2>' . $paragraphs,
    'contentformat' => FORMAT_HTML, 'display' => 0, 'printintro' => 0, 'printlastmodified' => 0,
    'displayoptions' => serialize(['printintro' => 0, 'printlastmodified' => 0]),
]);
$assignment = lab_module($course, 'assign', 'collector-assignment', 'Paste and submit your solution', [
    'intro' => '<p>Copy a sentence from the reading material, paste it into the online text editor and save your submission.</p>',
    'alwaysshowdescription' => 1, 'submissiondrafts' => 0, 'requiresubmissionstatement' => 0,
    'sendnotifications' => 0, 'sendlatenotifications' => 0, 'sendstudentnotifications' => 0,
    'duedate' => 0, 'cutoffdate' => 0, 'gradingduedate' => 0, 'allowsubmissionsfromdate' => 0,
    'grade' => 100, 'teamsubmission' => 0, 'requireallteammemberssubmit' => 0,
    'blindmarking' => 0, 'markingworkflow' => 0, 'markingallocation' => 0,
    'attemptreopenmethod' => 'none', 'maxattempts' => 1,
    'assignsubmission_onlinetext_enabled' => 1,
    'assignsubmission_onlinetext_wordlimit' => 0,
    'assignsubmission_onlinetext_wordlimit_enabled' => 0,
    'assignsubmission_file_enabled' => 0,
    'assignfeedback_comments_enabled' => 1,
]);
$quizoptions = [
    'intro' => '<p>Start an attempt and answer: 2 + 2 = ? Correct answer: 4.</p>',
    'timeopen' => 0, 'timeclose' => 0, 'timelimit' => 0, 'preferredbehaviour' => 'deferredfeedback',
    'attempts' => 0, 'attemptonlast' => 0, 'grademethod' => QUIZ_GRADEHIGHEST,
    'decimalpoints' => 2, 'questiondecimalpoints' => -1, 'questionsperpage' => 1,
    'shuffleanswers' => 0, 'sumgrades' => 0, 'grade' => 100,
    'overduehandling' => 'autosubmit', 'graceperiod' => 0,
    'quizpassword' => '', 'subnet' => '', 'browsersecurity' => '', 'delay1' => 0, 'delay2' => 0,
    'showuserpicture' => 0, 'showblocks' => 0, 'navmethod' => QUIZ_NAVMETHOD_FREE,
];
foreach (['attempt', 'correctness', 'maxmarks', 'marks', 'specificfeedback', 'generalfeedback', 'rightanswer', 'overallfeedback'] as $field) {
    foreach (['during', 'immediately', 'open', 'closed'] as $when) {
        $quizoptions[$field . $when] = 1;
    }
}
$quizcm = lab_module($course, 'quiz', 'collector-quiz', 'Simple quiz: 2 + 2', $quizoptions);
$quiz = $DB->get_record('quiz', ['id' => $quizcm->instance], '*', MUST_EXIST);
// Repair only question-bank entries referenced by this demo quiz. Keep questions,
// versions, quiz slots and attempts intact. A parent=0 category is a structural
// root and must not contain questions.
$brokenentries = $DB->get_records_sql("SELECT DISTINCT qbe.*
    FROM {quiz_slots} qs
    JOIN {question_references} qr ON qr.itemid = qs.id
    JOIN {question_bank_entries} qbe ON qbe.id = qr.questionbankentryid
    LEFT JOIN {question_categories} qc ON qc.id = qbe.questioncategoryid
    WHERE qs.quizid = :quizid AND qr.component = :component
      AND qr.questionarea = :area AND (qc.id IS NULL OR qc.parent = 0)",
    ['quizid' => $quiz->id, 'component' => 'mod_quiz', 'area' => 'slot']);
$needquestion = !$DB->record_exists('quiz_slots', ['quizid' => $quiz->id]);
if ($needquestion || $brokenentries) {
    $transaction = $DB->start_delegated_transaction();
    $bank = \core_question\local\bank\question_bank_helper::get_default_open_instance_system_type($course, true);
    $context = context_module::instance($bank->id);
    $category = question_get_default_category($context->id, true);
    if (!$category || !$category->parent) {
        throw new RuntimeException('Could not create a valid demo question category.');
    }
    foreach ($brokenentries as $entry) {
        $DB->set_field('question_bank_entries', 'questioncategoryid', $category->id, ['id' => $entry->id]);
        echo "Repaired demo question-bank entry {$entry->id}: category {$category->id}\n";
    }
    $transaction->allow_commit();
    if ($brokenentries) {
        purge_all_caches();
        foreach ($brokenentries as $entry) {
            foreach ($DB->get_records('question_versions', ['questionbankentryid' => $entry->id]) as $version) {
                question_bank::load_question($version->questionid);
            }
        }
        echo "Repaired demo questions load successfully.\n";
    }
}
if ($needquestion) {
    $form = (object)[
        'category' => $category->id . ',' . $context->id, 'name' => 'Two plus two',
        'questiontext' => ['text' => '<p>2 + 2 = ?</p>', 'format' => FORMAT_HTML],
        'generalfeedback' => ['text' => '<p>The answer is 4.</p>', 'format' => FORMAT_HTML],
        'defaultmark' => 1, 'penalty' => 0, 'usecase' => 0,
        'answer' => ['4'], 'fraction' => [1],
        'feedback' => [['text' => 'Correct!', 'format' => FORMAT_HTML]],
        'hint' => [],
    ];
    $question = question_bank::get_qtype('shortanswer')->save_question((object)['qtype' => 'shortanswer'], $form);
    question_bank::load_question($question->id);
    quiz_add_quiz_question($question->id, $quiz, 1, 1);
    \mod_quiz\quiz_settings::create($quiz->id)->get_grade_calculator()->recompute_quiz_sumgrades();
}

rebuild_course_cache($course->id, true);
$manifest = [
    'moodle' => $CFG->wwwroot,
    'course' => $CFG->wwwroot . '/course/view.php?id=' . $course->id,
    'reading' => $CFG->wwwroot . '/mod/page/view.php?id=' . $page->id,
    'assignment' => $CFG->wwwroot . '/mod/assign/view.php?id=' . $assignment->id,
    'quiz' => $CFG->wwwroot . '/mod/quiz/view.php?id=' . $quizcm->id,
    'playground' => $CFG->wwwroot . '/local/actioncollector/playground.php',
    'student_id' => $studentid, 'teacher_id' => $teacherid,
];
file_put_contents($CFG->dataroot . '/demo.json', json_encode($manifest, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
file_put_contents($CFG->dataroot . '/.actions-ready', 'ready');
echo json_encode($manifest, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n";
