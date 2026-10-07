<?php
namespace local_actioncollector;
defined('MOODLE_INTERNAL') || die();

final class hook_callbacks {
    public static function footer(\core\hook\output\before_standard_footer_html_generation $hook): void {
        global $USER, $PAGE;
        if (!isloggedin() || isguestuser() || !get_config('local_actioncollector', 'enabled')) {
            return;
        }
        $apiurl = get_config('local_actioncollector', 'apiurl');
        if (!$apiurl) { return; }
        $context = [
            'apiUrl' => rtrim($apiurl, '/'),
            'user' => [
                'student_id' => (int)$USER->id,
                'student' => fullname($USER),
                'email' => $USER->email,
                'course' => $PAGE->course->fullname,
            ],
        ];
        $json = json_encode($context, JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_UNESCAPED_UNICODE);
        $url = new \moodle_url('/local/actioncollector/collector.js', ['v' => 2026100700]);
        $html = '<script>window.actionCollectorConfig = ' . $json . ';</script>'
            . '<script src="' . s($url->out(false)) . '" defer></script>';
        $hook->add_html($html);
    }
}
