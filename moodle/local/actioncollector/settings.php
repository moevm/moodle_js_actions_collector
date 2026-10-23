<?php
defined('MOODLE_INTERNAL') || die();
if ($hassiteconfig) {
    $settings = new admin_settingpage('local_actioncollector', 'Action collector');
    $settings->add(new admin_setting_configcheckbox('local_actioncollector/enabled', 'Enable collection', 'Collect authenticated user actions.', 0));
    $settings->add(new admin_setting_configtext('local_actioncollector/apiurl', 'Collector API URL', 'Browser-accessible API URL, including /api. Use HTTPS for HTTPS Moodle.', '', PARAM_URL));
    $ADMIN->add('localplugins', $settings);
}
