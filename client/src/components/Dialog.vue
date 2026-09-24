<template>
  <v-dialog width="auto" :persistent="downloading" @after-leave="errorMessage = ''">
    <v-card text="Выберите файлы, которые вы хотите скачать:" title="Скачать">
      <v-container>
        <v-checkbox
          v-model="selected"
          :disabled="downloading"
          label="Выбранная статистика в формате json"
          value="statistics"
        ></v-checkbox>
        <v-checkbox
          v-model="selected"
          :disabled="downloading"
          label="Html-код страниц в формате json"
          value="pages"
        ></v-checkbox>
        <v-alert v-if="errorMessage" type="error" variant="tonal" role="alert">
          {{ errorMessage }}
        </v-alert>
      </v-container>
      <template v-slot:actions>
        <v-btn class="ms-auto" text="Отмена" :disabled="downloading" @click="$emit('close')"></v-btn>
        <v-btn
          color="primary"
          variant="tonal"
          text="Скачать"
          @click="download"
          :loading="downloading"
          :disabled="downloading || !selected.length"
        ></v-btn>
      </template>
    </v-card>
  </v-dialog>
</template>

<script>
import axios from "axios";
const STAT_FILE_URL = "/api/download/statistics";
const HTMLPAGE_FILE_URL = "/api/download/sessions";

export default {
  emits: ["close"],
  name: "Dialog",
  props: ["params"],
  data() {
    return {
      selected: ["statistics"],
      downloading: false,
      errorMessage: "",
    };
  },
  methods: {
    getUrl(file){
      if (file === "statistics") return STAT_FILE_URL
      return HTMLPAGE_FILE_URL
    },
    async download() {
      if (this.downloading || !this.selected.length) return;

      this.downloading = true;
      this.errorMessage = "";
      const files = [...this.selected];
      const params = {...this.params};
      const failedFiles = [];
      const errors = [];

      try {
        for (const file of files) {
          try {
            const response = await axios.get(this.getUrl(file), {
              params,
              responseType: "blob",
            });
            const url = URL.createObjectURL(response.data);
            const link = document.createElement("a");
            try {
              link.href = url;
              link.download = `${file}.json`;
              document.body.appendChild(link);
              link.click();
            } finally {
              link.remove();
              // Give the browser time to start reading the download.
              setTimeout(() => URL.revokeObjectURL(url), 60000);
            }
          } catch (error) {
            failedFiles.push(file);
            const status = error.response ? ` (HTTP ${error.response.status})` : "";
            errors.push(`Не удалось скачать ${file}.json${status}. Повторите попытку.`);
            console.error("Ошибка скачивания:", error);
          }
        }
      } finally {
        this.downloading = false;
      }

      if (failedFiles.length) {
        this.selected = failedFiles;
        this.errorMessage = errors.join(" ");
      } else {
        this.$emit("close");
      }
    },
  },
};
</script>

<style scoped>
@import "@/colors.css";
</style>
