<?php
require_once(__DIR__ . '/../../config.php');
$course = $DB->get_record('course', ['shortname' => 'COLLECTOR-DEMO'], '*', MUST_EXIST);
require_login($course);
$PAGE->set_url(new moodle_url('/local/actioncollector/playground.php'));
$PAGE->set_course($course);
$PAGE->set_context(context_course::instance($course->id));
$PAGE->set_title('Collector playground');
$PAGE->set_heading('Collector playground');
echo $OUTPUT->header();
echo '<p>Copy text into the field, click the button, scroll and switch tabs. Events are sent every two seconds.</p>';
echo '<p id="copy-source">Sample solution: 2 + 2 = 4. Select and copy this sentence.</p>';
echo '<button type="button" id="collector-demo-button" class="btn btn-primary">Demo button</button>';
echo '<p><textarea id="collector-demo-answer" name="demo-answer" rows="5" cols="60" aria-label="Demo answer"></textarea></p>';
echo '<div style="min-height:1400px;background:linear-gradient(#eef,#fff)"><p>Scroll down.</p></div>';
echo html_writer::link(new moodle_url('/course/view.php', ['id' => $course->id]), 'Return to demo course');
echo $OUTPUT->footer();
