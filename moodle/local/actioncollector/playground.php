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
// Optional demo fixture for browser privacy tests; never used on course pages.
$privacyprobe = optional_param('privacy_probe', '', PARAM_RAW);
if (preg_match('/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/D', $privacyprobe)) {
    $privatevalue = s('private-' . $privacyprobe);
    echo '<div id="privacy-fixture">';
    echo '<input id="privacy-password" type="password" value="' . $privatevalue . '">';
    echo '<textarea id="privacy-text">' . $privatevalue . '</textarea>';
    echo '<div id="privacy-editor" contenteditable="true">' . $privatevalue . '</div>';
    echo '<p id="privacy-public">Public fixture marker</p></div>';
}

echo '<p>Copy text into the field, click the button, scroll and switch tabs. Events are sent every two seconds.</p>';
echo '<p id="copy-source">Sample solution: 2 + 2 = 4. Select and copy this sentence.</p>';
echo '<button type="button" id="collector-demo-button" class="btn btn-primary">Demo button</button>';
echo '<p><textarea id="collector-demo-answer" name="demo-answer" rows="5" cols="60" aria-label="Demo answer"></textarea></p>';
echo '<div style="min-height:1400px;background:linear-gradient(#eef,#fff)"><p>Scroll down.</p></div>';
echo html_writer::link(new moodle_url('/course/view.php', ['id' => $course->id]), 'Return to demo course');
echo $OUTPUT->footer();
